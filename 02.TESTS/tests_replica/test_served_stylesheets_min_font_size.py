import re


SERVED_STYLESHEETS = (
    ("application.STYLESHEET", "application"),
    ("universal_presentation_seed.STYLESHEET", "universal_presentation_seed"),
)


def test_served_stylesheets_have_no_text_below_11px():
    from nodelang import application, universal_presentation_seed

    sheets = {
        "application.STYLESHEET": application.STYLESHEET,
        "universal_presentation_seed.STYLESHEET": universal_presentation_seed.STYLESHEET,
    }
    violations = []
    for sheet_name, sheet in sheets.items():
        for declaration in re.finditer(r"font-size\s*:\s*([^;}]+)", sheet):
            value = declaration.group(1)
            for size in re.finditer(r"(?<![\w.-])(\d+(?:\.\d+)?)px\b", value):
                numeric_size = float(size.group(1))
                if numeric_size < 11:
                    violations.append(
                        f"{sheet_name}: font-size:{value.strip()} at offset {declaration.start()}"
                    )

    assert violations == []
