//! Small, in-process semantic passes learned from Ruff/Pyright and Oxc/tsc.
//! No checker executable, source execution, or prose assertion participates.
//! This is deliberately a bounded lexical/type pass, not Python/TS equivalence.
use crate::{children, text, Diagnostic};
use std::collections::{BTreeMap, BTreeSet};
use tree_sitter::{Node, Parser};

#[derive(Clone)]
struct Binding {
    name: String,
    scope: usize,
    line: usize,
    col: usize,
    kind: String,
    used: bool,
}
#[derive(Default)]
struct Scope {
    parent: Option<usize>,
    bindings: BTreeMap<String, usize>,
    function: bool,
    class: bool,
    comprehension: bool,
}
#[derive(Clone)]
struct Signature {
    scope: usize,
    name: String,
    min: usize,
    max: Option<usize>,
    parameters: Vec<String>,
    positional: Vec<String>,
    keyword_variadic: bool,
    required: BTreeSet<String>,
    types: BTreeMap<String, String>,
}
#[derive(Clone)]
struct Call {
    name: String,
    scope: usize,
    count: usize,
    keywords: Vec<String>,
    arguments: Vec<(Option<String>, Option<String>)>,
    line: usize,
    col: usize,
}
struct Pass<'a> {
    file: &'a str,
    language: &'a str,
    source: &'a str,
    scopes: Vec<Scope>,
    bindings: Vec<Binding>,
    refs: Vec<(String, usize, usize, usize)>,
    signatures: Vec<Signature>,
    calls: Vec<Call>,
    diagnostics: Vec<Diagnostic>,
}
impl Pass<'_> {
    fn diag(&mut self, code: &str, line: usize, col: usize, message: String, help: &str) {
        self.diagnostics.push(Diagnostic {
            code: code.into(),
            note: crate::explain(code).unwrap_or("semantic pass").into(),
            language: self.language.into(),
            file: self.file.into(),
            line,
            column: col,
            message,
            help: help.into(),
        });
    }
    fn at(&mut self, code: &str, node: Node<'_>, message: String, help: &str) {
        self.diag(
            code,
            node.start_position().row + 1,
            node.start_position().column + 1,
            message,
            help,
        );
    }
    fn bind(&mut self, node: Node<'_>, scope: usize, kind: &str) {
        if node.kind() != "identifier" && node.kind() != "shorthand_property_identifier_pattern" {
            return;
        }
        let name = text(node, self.source).to_string();
        if let Some(&old) = self.scopes[scope].bindings.get(&name) {
            let b = &self.bindings[old];
            if kind == "function"
                || kind == "class"
                || (self.language != "python" && kind == "variable")
                || b.kind == "import"
            {
                self.at(
                    "E0021",
                    node,
                    format!("`{name}` redefines a binding in the same lexical scope"),
                    "keep one definition or choose a distinct name",
                );
            }
            return;
        }
        let id = self.bindings.len();
        self.scopes[scope].bindings.insert(name.clone(), id);
        let mut ancestor = node.parent();
        let mut exported = false;
        while let Some(p) = ancestor {
            if p.kind() == "export_statement" {
                exported = true;
                break;
            }
            if matches!(p.kind(), "statement_block" | "function_definition") {
                break;
            }
            ancestor = p.parent();
        }
        self.bindings.push(Binding {
            name,
            scope,
            line: node.start_position().row + 1,
            col: node.start_position().column + 1,
            kind: kind.into(),
            used: exported,
        });
    }
    fn pattern(&mut self, node: Node<'_>, scope: usize, kind: &str) {
        if matches!(
            node.kind(),
            "identifier" | "shorthand_property_identifier_pattern"
        ) {
            self.bind(node, scope, kind);
            return;
        }
        if matches!(
            node.kind(),
            "attribute" | "member_expression" | "subscript" | "subscript_expression"
        ) {
            self.walk(node, scope);
            return;
        }
        for ch in children(node) {
            if ch.kind().contains("type") {
                self.walk(ch, scope);
                continue;
            }
            if node.kind() == "pair_pattern" && node.child_by_field_name("key") == Some(ch) {
                continue;
            }
            if matches!(
                node.kind(),
                "default_parameter" | "typed_default_parameter" | "assignment_pattern"
            ) && node
                .child_by_field_name("value")
                .or_else(|| node.child_by_field_name("right"))
                == Some(ch)
            {
                let defaults_scope = if self.language == "python" {
                    self.scopes[scope].parent.unwrap_or(scope)
                } else {
                    scope
                };
                self.walk(ch, defaults_scope);
            } else {
                self.pattern(ch, scope, kind);
            }
        }
    }
    fn resolve(&self, name: &str, mut scope: usize) -> Option<usize> {
        loop {
            if let Some(id) = self.scopes[scope].bindings.get(name) {
                return Some(*id);
            }
            scope = self.scopes[scope].parent?;
        }
    }
    fn function(&mut self, node: Node<'_>, scope: usize) {
        let declared = node.child_by_field_name("name");
        // Assigned lambdas/arrows have their name on the declarator, not on
        // the function node. The declarator still owns the single binding.
        let assigned = node
            .parent()
            .filter(|p| matches!(p.kind(), "assignment" | "variable_declarator"))
            .and_then(|p| {
                p.child_by_field_name("left")
                    .or_else(|| p.child_by_field_name("name"))
            })
            .filter(|n| n.kind() == "identifier");
        let name = assigned.or(declared);
        if let Some(n) = declared {
            self.bind(n, scope, "function");
        }
        let id = self.scopes.len();
        let parent = if self.language == "python" && self.scopes[scope].class {
            self.scopes[scope].parent.unwrap_or(scope)
        } else {
            scope
        };
        self.scopes.push(Scope {
            parent: Some(parent),
            function: true,
            ..Scope::default()
        });
        let params = node
            .child_by_field_name("parameters")
            .or_else(|| node.child_by_field_name("parameter"));
        if let Some(params) = params {
            let parts = if params.kind() == "identifier" {
                vec![params]
            } else {
                children(params)
            };
            let mut min = 0;
            let mut keyword_variadic = false;
            let mut variadic = false;
            let mut parameter_names = vec![];
            let mut positional = vec![];
            let mut keyword_only = false;
            let mut required = BTreeSet::new();
            let mut types = BTreeMap::new();
            for p in parts {
                if p.kind() == "keyword_separator" {
                    keyword_only = true;
                }
                if matches!(
                    p.kind(),
                    "type_parameter"
                        | "type_parameters"
                        | "keyword_separator"
                        | "positional_separator"
                ) {
                    continue;
                }
                let raw = text(p, self.source);
                if raw.starts_with('*') || raw.starts_with("...") {
                    keyword_variadic |= raw.starts_with("**");
                    variadic |= !raw.starts_with("**");
                    keyword_only = true;
                } else {
                    if let Some(name) = parameter_name(p, self.source).or_else(|| {
                        (self.language != "python").then(|| format!("#{}", positional.len()))
                    }) {
                        if let Some(annotation) = p.child_by_field_name("type") {
                            types.insert(
                                name.clone(),
                                text(annotation, self.source)
                                    .trim_start_matches(':')
                                    .trim()
                                    .to_string(),
                            );
                        }
                        parameter_names.push(name.clone());
                        if !keyword_only {
                            positional.push(name.clone());
                        }
                        if !raw.contains('=') && !raw.contains('?') {
                            required.insert(name);
                        }
                    }
                    if !raw.contains('=') && !raw.contains('?') {
                        min += 1;
                    }
                }
                self.pattern(p, id, "parameter");
            }
            if let Some(name) = name {
                self.signatures.push(Signature {
                    scope,
                    name: text(name, self.source).into(),
                    min,
                    max: if variadic {
                        None
                    } else {
                        Some(positional.len())
                    },
                    parameters: parameter_names,
                    positional,
                    keyword_variadic,
                    required,
                    types,
                });
            }
        }
        if let Some(annotation) = node.child_by_field_name("return_type") {
            self.walk(annotation, scope);
        }
        if let Some(body) = node.child_by_field_name("body") {
            let annotation = node.child_by_field_name("return_type");
            let explicit = annotation
                .map(|n| text(n, self.source))
                .unwrap_or("")
                .trim_start_matches(':')
                .trim();
            if matches!(body.kind(), "block" | "statement_block") {
                let wants = (!explicit.is_empty()
                    && !matches!(explicit, "None" | "void" | "undefined" | "Any"))
                    || has_value_return(body, self.source);
                if wants && !terminates(body, self.source) {
                    self.at(
                        "E0024",
                        node,
                        "function may finish without returning its result".into(),
                        "return a result on every branch or declare a void contract",
                    );
                }
                if !explicit.is_empty() {
                    self.return_types(body, explicit);
                }
            }
            self.walk(body, id);
        }
    }
    fn return_types(&mut self, node: Node<'_>, expected: &str) {
        if matches!(
            node.kind(),
            "function_definition"
                | "function_declaration"
                | "arrow_function"
                | "function_expression"
        ) {
            return;
        }
        if node.kind() == "return_statement" {
            if let Some(expr) = children(node).first() {
                if let Some(actual) = literal_type(*expr) {
                    if !compatible(expected, actual) {
                        self.at(
                            "E0026",
                            *expr,
                            format!("return type `{actual}` does not match `{expected}`"),
                            "return the declared type or correct the contract",
                        );
                    }
                }
            }
        }
        for ch in children(node) {
            self.return_types(ch, expected);
        }
    }
    fn import(&mut self, node: Node<'_>, scope: usize) {
        if node.kind() == "import_from_statement"
            && node
                .child_by_field_name("module_name")
                .is_some_and(|n| text(n, self.source) == "__future__")
        {
            return;
        }
        let from = node.kind() == "import_from_statement";
        for ch in children(node) {
            if from && node.child_by_field_name("module_name") == Some(ch) {
                continue;
            }
            if ch.kind() == "aliased_import" {
                if let Some(n) = ch.child_by_field_name("alias") {
                    self.bind(n, scope, "import");
                }
            } else if ch.kind() == "dotted_name" {
                if let Some(n) = children(ch).first() {
                    self.bind(*n, scope, "import");
                }
            } else if matches!(
                ch.kind(),
                "import_clause" | "named_imports" | "namespace_import" | "import_specifier"
            ) {
                if ch.kind() == "import_specifier" {
                    if let Some(n) = ch
                        .child_by_field_name("alias")
                        .or_else(|| ch.child_by_field_name("name"))
                    {
                        self.bind(n, scope, "import");
                    }
                } else {
                    self.import(ch, scope);
                }
            } else if ch.kind() == "identifier" {
                self.bind(ch, scope, "import");
            }
        }
    }
    fn loop_statement(&mut self, node: Node<'_>, scope: usize) {
        let lexical = node.child_by_field_name("kind")
            .is_some_and(|n| matches!(text(n, self.source), "const" | "let"))
            || node.child_by_field_name("initializer")
                .is_some_and(|n| n.kind() == "lexical_declaration");
        let scope = if self.language != "python" && lexical {
            let id = self.scopes.len();
            self.scopes.push(Scope {
                parent: Some(scope),
                function: self.scopes[scope].function,
                ..Scope::default()
            });
            id
        } else {
            scope
        };
        if let Some(left) = node.child_by_field_name("left") {
            if self.language == "python" || node.child_by_field_name("kind").is_some() {
                self.pattern(left, scope, "variable");
            } else {
                self.walk(left, scope);
            }
        }
        for child in children(node) {
            if node.child_by_field_name("left") != Some(child) {
                self.walk(child, scope);
            }
        }
    }
    fn catch_clause(&mut self, node: Node<'_>, scope: usize) {
        let id = self.scopes.len();
        self.scopes.push(Scope {
            parent: Some(scope),
            function: self.scopes[scope].function,
            ..Scope::default()
        });
        if let Some(parameter) = node.child_by_field_name("parameter") {
            self.pattern(parameter, id, "parameter");
        }
        if let Some(body) = node.child_by_field_name("body") {
            for child in children(body) {
                self.walk(child, id);
            }
        }
    }
    fn walk(&mut self, node: Node<'_>, scope: usize) {
        let k = node.kind();
        if k.contains("comment") || node.is_error() {
            return;
        }
        // This grammar represents future directives as their own statement,
        // with no module_name field and no runtime name binding.
        if k == "future_import_statement" {
            return;
        }
        if matches!(k, "nonlocal_statement" | "global_statement") {
            for name in children(node)
                .into_iter()
                .filter(|n| n.kind() == "identifier")
            {
                let value = text(name, self.source);
                let parent = if k == "global_statement" {
                    0
                } else {
                    self.scopes[scope].parent.unwrap_or(0)
                };
                if let Some(binding) = self.resolve(value, parent) {
                    self.scopes[scope].bindings.insert(value.into(), binding);
                }
            }
            return;
        }
        if k == "string" {
            let mut parent = node.parent();
            let mut annotation = false;
            while let Some(p) = parent {
                if matches!(p.kind(), "type" | "type_annotation") {
                    annotation = true;
                    break;
                }
                if matches!(
                    p.kind(),
                    "assignment" | "function_definition" | "expression_statement" | "argument_list"
                ) {
                    break;
                }
                parent = p.parent();
            }
            if annotation {
                if let Some(value) = crate::scalar(node, self.source) {
                    for name in value
                        .split(|c: char| !c.is_alphanumeric() && c != '_')
                        .filter(|s| !s.is_empty() && !s.chars().next().unwrap().is_numeric())
                    {
                        self.refs.push((
                            name.into(),
                            scope,
                            node.start_position().row + 1,
                            node.start_position().column + 1,
                        ));
                    }
                }
            }
        }
        if matches!(
            k,
            "list_comprehension"
                | "dictionary_comprehension"
                | "set_comprehension"
                | "generator_expression"
        ) {
            let id = self.scopes.len();
            self.scopes.push(Scope {
                parent: Some(scope),
                function: true,
                comprehension: true,
                ..Scope::default()
            });
            for child in children(node) {
                self.walk(child, id);
            }
            return;
        }
        if matches!(
            k,
            "function_definition"
                | "function_declaration"
                | "function_expression"
                | "generator_function_declaration"
                | "arrow_function"
                | "lambda"
                | "method_definition"
        ) {
            self.function(node, scope);
            return;
        }
        if matches!(
            k,
            "import_statement" | "import_from_statement" | "import_clause" | "named_imports"
        ) {
            self.import(node, scope);
            return;
        }
        if matches!(k, "class_definition" | "class_declaration") {
            if let Some(name) = node.child_by_field_name("name") {
                self.bind(name, scope, "class");
            }
            let id = self.scopes.len();
            self.scopes.push(Scope {
                parent: Some(scope),
                class: true,
                ..Scope::default()
            });
            for ch in children(node) {
                if node.child_by_field_name("name") != Some(ch) {
                    self.walk(ch, id);
                }
            }
            return;
        }
        if matches!(k, "assignment" | "variable_declarator" | "named_expression") {
            if let Some(rhs) = node
                .child_by_field_name("right")
                .or_else(|| node.child_by_field_name("value"))
            {
                if let Some(ann) = node.child_by_field_name("type") {
                    if let Some(actual) = literal_type(rhs) {
                        let expected = text(ann, self.source).trim_start_matches(':').trim();
                        if !compatible(expected, actual) {
                            self.at(
                                "E0026",
                                rhs,
                                format!("value type `{actual}` does not match `{expected}`"),
                                "supply a value of the declared type",
                            );
                        }
                    }
                }
                self.walk(rhs, scope);
            }
            if let Some(lhs) = node
                .child_by_field_name("left")
                .or_else(|| node.child_by_field_name("name"))
            {
                self.pattern(lhs, scope, "variable");
            }
            return;
        }
        if matches!(k, "for_statement" | "for_in_statement" | "for_in_clause") {
            self.loop_statement(node, scope);
            return;
        }
        if k == "catch_clause" {
            self.catch_clause(node, scope);
            return;
        }
        if k == "except_clause" {
            if let Some(alias) = node.child_by_field_name("alias") {
                self.pattern(alias, scope, "variable");
            }
            for child in children(node) {
                if node.child_by_field_name("alias") != Some(child) {
                    self.walk(child, scope);
                }
            }
            return;
        }
        if k == "as_pattern" {
            if let Some(alias) = node.child_by_field_name("alias") {
                self.pattern(alias, scope, "variable");
            }
            for child in children(node) {
                if node.child_by_field_name("alias") != Some(child) {
                    self.walk(child, scope);
                }
            }
            return;
        }
        if matches!(k, "block" | "statement_block" | "module" | "program") {
            let active = if self.language != "python" && k == "statement_block" {
                let id = self.scopes.len();
                let function = self.scopes[scope].function;
                self.scopes.push(Scope {
                    parent: Some(scope),
                    function,
                    ..Scope::default()
                });
                id
            } else {
                scope
            };
            let mut dead = false;
            for ch in children(node) {
                if dead && !ch.kind().contains("comment") {
                    self.at(
                        "E0023",
                        ch,
                        "statement is unreachable after a terminating statement".into(),
                        "remove it or move it before the terminating branch",
                    );
                }
                self.walk(ch, active);
                if terminates(ch, self.source) {
                    dead = true;
                }
            }
            return;
        }
        if matches!(k, "call" | "call_expression") {
            if let (Some(fun), Some(args)) = (
                node.child_by_field_name("function"),
                node.child_by_field_name("arguments"),
            ) {
                if fun.kind() == "identifier"
                    && !children(args).iter().any(|a| {
                        matches!(
                            a.kind(),
                            "list_splat" | "dictionary_splat" | "spread_element"
                        )
                    })
                {
                    self.calls.push(Call {
                        name: text(fun, self.source).into(),
                        scope,
                        count: children(args)
                            .iter()
                            .filter(|a| a.kind() != "keyword_argument")
                            .count(),
                        keywords: children(args)
                            .iter()
                            .filter(|a| a.kind() == "keyword_argument")
                            .filter_map(|a| a.child_by_field_name("name"))
                            .map(|n| text(n, self.source).to_string())
                            .collect(),
                        arguments: children(args)
                            .into_iter()
                            .map(|arg| {
                                let keyword = arg
                                    .child_by_field_name("name")
                                    .filter(|_| arg.kind() == "keyword_argument")
                                    .map(|n| text(n, self.source).to_string());
                                let value = if keyword.is_some() {
                                    arg.child_by_field_name("value").unwrap_or(arg)
                                } else {
                                    arg
                                };
                                (keyword, literal_type(value).map(str::to_string))
                            })
                            .collect(),
                        line: node.start_position().row + 1,
                        col: node.start_position().column + 1,
                    });
                }
            }
        }
        if matches!(
            k,
            "identifier" | "type_identifier" | "shorthand_property_identifier"
        ) {
            let parent = node.parent();
            let is_key = parent.is_some_and(|p| {
                matches!(
                    p.kind(),
                    "pair"
                        | "pair_pattern"
                        | "keyword_argument"
                        | "attribute"
                        | "member_expression"
                        | "jsx_attribute"
                ) && (p.kind() != "pair" || self.language != "python")
                    && (p.child_by_field_name("key") == Some(node)
                        || p.child_by_field_name("attribute") == Some(node)
                        || p.child_by_field_name("property") == Some(node)
                        || p.child_by_field_name("name") == Some(node))
            });
            let is_type = parent.is_some_and(|p| {
                matches!(
                    p.kind(),
                    "jsx_opening_element" | "jsx_closing_element" | "jsx_self_closing_element"
                ) && !text(node, self.source)
                    .chars()
                    .next()
                    .is_some_and(char::is_uppercase)
            });
            if !is_key && !is_type {
                self.refs.push((
                    text(node, self.source).into(),
                    scope,
                    node.start_position().row + 1,
                    node.start_position().column + 1,
                ));
            }
            return;
        }
        for ch in children(node) {
            self.walk(ch, scope);
        }
    }
    fn finish(mut self) -> Vec<Diagnostic> {
        let builtins = builtins(self.language);
        for (name, scope, line, col) in self.refs.clone() {
            if let Some(id) = self.resolve(&name, scope) {
                let binding = &self.bindings[id];
                if binding.scope == scope
                    && !self.scopes[scope].comprehension
                    && binding.kind == "variable"
                    && (line, col) < (binding.line, binding.col)
                {
                    self.diag("E0020", line, col, format!("name `{name}` is read before its local binding"),
                        "bind the value before reading it; a later assignment cannot initialize this read");
                }
                self.bindings[id].used = true;
            } else if !builtins.contains(name.as_str()) {
                self.diag(
                    "E0020",
                    line,
                    col,
                    format!("undefined name `{name}`"),
                    "bind this name in its lexical scope or import its owner",
                );
            }
        }
        for binding in self.bindings.clone() {
            if !binding.used
                && !binding.name.starts_with('_')
                && (binding.kind == "import"
                    || (binding.kind == "variable"
                        && (self.scopes[binding.scope].function || self.language != "python")))
            {
                self.diag(
                    "E0022",
                    binding.line,
                    binding.col,
                    format!("unused {} `{}`", binding.kind, binding.name),
                    "use the binding or remove it",
                );
            }
        }
        for Call {
            name,
            scope,
            count,
            keywords,
            arguments,
            line,
            col,
        } in self.calls.clone()
        {
            if let Some(binding) = self.resolve(&name, scope) {
                let owner = self.bindings[binding].scope;
                if let Some(sig) = self
                    .signatures
                    .iter()
                    .find(|s| s.name == name && s.scope == owner)
                    .cloned()
                {
                    let assigned: BTreeSet<_> = sig
                        .positional
                        .iter()
                        .take(count)
                        .cloned()
                        .chain(keywords.iter().cloned())
                        .collect();
                    let keyword_error = keywords.iter().any(|key| {
                        sig.positional.iter().take(count).any(|p| p == key)
                            || (!sig.keyword_variadic && !sig.parameters.contains(key))
                    }) || keywords.iter().collect::<BTreeSet<_>>().len()
                        != keywords.len();
                    let missing = sig.required.iter().any(|key| !assigned.contains(key));
                    if missing || keyword_error || sig.max.is_some_and(|max| count > max) {
                        self.diag(
                            "E0025",
                            line,
                            col,
                            format!(
                                "call `{name}` has {count} arguments; expected {}..{}",
                                sig.min,
                                sig.max
                                    .map(|n| n.to_string())
                                    .unwrap_or_else(|| "unbounded".into())
                            ),
                            "match the function's declared parameters",
                        );
                    }
                    for (index, (keyword, actual)) in arguments.iter().enumerate() {
                        let parameter = keyword.as_ref().or_else(|| sig.positional.get(index));
                        if let (Some(expected), Some(actual)) =
                            (parameter.and_then(|p| sig.types.get(p)), actual)
                        {
                            if !compatible(expected, actual) {
                                self.diag("E0026", line, col, format!("call `{name}` argument type `{actual}` does not match `{expected}`"),
                                    "pass a value of the declared parameter type");
                            }
                        }
                    }
                }
            }
        }
        self.diagnostics
    }
}
fn parameter_name(node: Node<'_>, source: &str) -> Option<String> {
    if node.kind() == "identifier" {
        return Some(text(node, source).into());
    }
    if let Some(name) = node
        .child_by_field_name("name")
        .or_else(|| node.child_by_field_name("left"))
        .or_else(|| node.child_by_field_name("pattern"))
    {
        return parameter_name(name, source);
    }
    children(node)
        .into_iter()
        .find(|n| n.kind() == "identifier")
        .map(|n| text(n, source).into())
}
fn literal_type(node: Node<'_>) -> Option<&'static str> {
    match node.kind() {
        "string" | "string_literal" | "template_string" => Some("string"),
        "integer" | "float" | "number" => Some("number"),
        "true" | "false" => Some("boolean"),
        "none" | "null" => Some("null"),
        _ => None,
    }
}
fn compatible(expected: &str, actual: &str) -> bool {
    match expected.trim() {
        "str" | "string" => actual == "string",
        "int" | "float" | "number" => actual == "number",
        "bool" | "boolean" => actual == "boolean",
        "None" | "null" => actual == "null",
        _ => true,
    }
}
fn has_value_return(node: Node<'_>, source: &str) -> bool {
    if matches!(
        node.kind(),
        "function_definition" | "function_declaration" | "arrow_function" | "function_expression"
            | "method_definition" | "generator_function_declaration"
    ) {
        return false;
    }
    if node.kind() == "return_statement" {
        return !children(node).is_empty()
            && !matches!(
                text(node, source).trim(),
                "return None" | "return null;" | "return undefined;"
            );
    }
    children(node)
        .into_iter()
        .any(|n| has_value_return(n, source))
}
fn terminates(node: Node<'_>, source: &str) -> bool {
    match node.kind() {
        "return_statement" | "raise_statement" | "throw_statement" | "break_statement"
        | "continue_statement" => true,
        "block" | "statement_block" => children(node).into_iter().any(|n| terminates(n, source)),
        "with_statement" => node
            .child_by_field_name("body")
            .is_some_and(|n| terminates(n, source)),
        "try_statement" => {
            let parts = children(node);
            let finally = parts.iter().find(|n| matches!(n.kind(), "finally_clause"));
            // A terminating finally supersedes both successful and exceptional
            // paths; a nonterminating finally preserves their previous outcome.
            if finally.is_some_and(|n| terminates(*n, source)) {
                return true;
            }
            let success = node
                .child_by_field_name("body")
                .is_some_and(|n| terminates(n, source))
                || parts
                    .iter()
                    .find(|n| n.kind() == "else_clause")
                    .is_some_and(|n| terminates(*n, source));
            let handlers = parts
                .iter()
                .filter(|n| matches!(n.kind(), "except_clause" | "catch_clause"));
            success && handlers.into_iter().all(|n| terminates(*n, source))
        }
        "except_clause" | "catch_clause" | "finally_clause" => node
            .child_by_field_name("body")
            .or_else(|| {
                children(node)
                    .into_iter()
                    .find(|n| matches!(n.kind(), "block" | "statement_block"))
            })
            .is_some_and(|n| terminates(n, source)),
        "if_statement" => {
            let body = node
                .child_by_field_name("consequence")
                .or_else(|| node.child_by_field_name("body"));
            let alt = node.child_by_field_name("alternative");
            body.zip(alt)
                .is_some_and(|(a, b)| terminates(a, source) && terminates(b, source))
        }
        "else_clause" | "elif_clause" => children(node)
            .last()
            .is_some_and(|n| terminates(*n, source)),
        _ => false,
    }
}
fn builtins(language: &str) -> BTreeSet<&'static str> {
    let py="abs aiter all anext any ascii bin bool breakpoint bytearray bytes callable chr classmethod compile complex delattr dict dir divmod enumerate eval exec filter float format frozenset getattr globals hasattr hash help hex id input int isinstance issubclass iter len list locals map max memoryview min next object oct open ord pow print property range repr reversed round set setattr slice sorted staticmethod str sum super tuple type vars zip __import__ __name__ __file__ __package__ __doc__ __builtins__ True False None Ellipsis NotImplemented BaseException Exception ValueError TypeError RuntimeError KeyError AttributeError ImportError OSError IOError StopIteration NotImplementedError FileNotFoundError FileExistsError PermissionError TimeoutError AssertionError IndexError UnicodeError UnicodeDecodeError ZeroDivisionError NameError UnboundLocalError SystemExit GeneratorExit Warning RecursionError ConnectionError ConnectionRefusedError KeyboardInterrupt SyntaxError EOFError";
    let js="Array ArrayBuffer Atomics BigInt Boolean Date Error EvalError Function Infinity Intl JSON Map Math NaN Number Object Promise Proxy RangeError ReferenceError Reflect RegExp Set String Symbol SyntaxError TypeError URIError WeakMap WeakSet WeakRef arguments console decodeURI decodeURIComponent encodeURI encodeURIComponent escape eval globalThis isFinite isNaN parseFloat parseInt undefined unescape window document navigator location history localStorage sessionStorage fetch alert confirm prompt setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame URL URLSearchParams Blob File FormData Headers Request Response AbortController AbortSignal Event CustomEvent HTMLElement Node TextEncoder TextDecoder Buffer process module exports require __dirname __filename React";
    if language == "python" { py } else { js }
        .split_whitespace()
        .collect()
}
pub fn check(sources: &[(String, String)]) -> Vec<Diagnostic> {
    let mut diagnostics = vec![];
    for (file, source) in sources {
        let language = crate::language_name(file);
        if !matches!(language, "python" | "javascript" | "typescript") {
            continue;
        }
        let Some(grammar) = crate::grammar(language, file) else {
            continue;
        };
        let mut parser = Parser::new();
        if parser.set_language(&grammar).is_err() {
            continue;
        }
        let Some(tree) = parser.parse(source, None) else {
            continue;
        };
        let mut pass = Pass {
            file,
            language,
            source,
            scopes: vec![Scope::default()],
            bindings: vec![],
            refs: vec![],
            signatures: vec![],
            calls: vec![],
            diagnostics: vec![],
        };
        pass.walk(tree.root_node(), 0);
        diagnostics.extend(pass.finish());
    }
    diagnostics.sort();
    diagnostics.dedup();
    diagnostics
}

#[cfg(test)]
mod presence_builtin_tests {
    #[test]
    fn python_unicode_decode_error_builtin_without_import() {
        let valid = "def decode(payload):\n    try:\n        return payload.decode('utf-8')\n    except UnicodeDecodeError:\n        return None\n";
        let diagnostics = super::check(&[("presence.py".into(), valid.into())]);
        assert!(!diagnostics.iter().any(|d| d.code == "E0020"), "{diagnostics:?}");
        let invalid = valid.replace("UnicodeDecodeError", "UnicodeDecodeErorr");
        let diagnostics = super::check(&[("presence.py".into(), invalid)]);
        assert!(diagnostics.iter().any(|d| d.code == "E0020" && d.message.contains("UnicodeDecodeErorr")));
    }
}
