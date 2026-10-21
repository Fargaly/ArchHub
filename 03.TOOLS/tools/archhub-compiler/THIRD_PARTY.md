# Third-party dependencies

Dependencies are linked from pinned crates in Cargo.lock. Licenses are retained below; no rustc, Ruff, Oxc, Pyright or TypeScript implementation source is copied.

These five published crates omit their license text. The release collector uses
the retained upstream license at the crate's recorded VCS revision, verifies its
SHA-256, and binds these inputs into source provenance. No build fetch occurs.
The sequel crate records a dirty VCS tree; its upstream license revision is
retained without claiming its published implementation equals that upstream tree.

| Package | Version | Retained input | Pinned source | SHA-256 |
|---|---|---|---|---|
| tree-sitter-html | 0.23.2 | licenses/tree-sitter-html-0.23.2-LICENSE.txt | https://raw.githubusercontent.com/tree-sitter/tree-sitter-html/5a5ca8551a179998360b4a4ca2c0f366a35acc03/LICENSE | 2e0110e07abef7c2548b26ec9d6969775617ca539a0dc8dbeeb14d6452c711d1 |
| tree-sitter-json | 0.24.8 | licenses/tree-sitter-json-0.24.8-LICENSE.txt | https://raw.githubusercontent.com/tree-sitter/tree-sitter-json/ee35a6ebefcef0c5c416c0d1ccec7370cfca5a24/LICENSE | 2e0110e07abef7c2548b26ec9d6969775617ca539a0dc8dbeeb14d6452c711d1 |
| tree-sitter-sequel | 0.3.11 | licenses/tree-sitter-sequel-0.3.11-LICENSE.txt | https://raw.githubusercontent.com/derekstride/tree-sitter-sql/7b51ecda191d36b92f5a90a8d1bc3faef1c7b8b8/LICENSE | 3b3e4e4252d5d7d1c18e1257005f23242bf0580ad619204fd093c99b8c56748d |
| tree-sitter-toml-ng | 0.7.0 | licenses/tree-sitter-toml-ng-0.7.0-LICENSE.txt | https://raw.githubusercontent.com/tree-sitter-grammars/tree-sitter-toml/64b56832c2cffe41758f28e05c756a3a98d16f41/LICENSE | b727eee929bee836e8102cecf749a795b199f291b58c885bcd81cae727ac5a46 |
| tree-sitter-typescript | 0.23.2 | licenses/tree-sitter-typescript-0.23.2-LICENSE.txt | https://raw.githubusercontent.com/tree-sitter/tree-sitter-typescript/f975a621f4e7f532fe322e13c4f79495e0a7b2e7/LICENSE | 49bf33cf78ef5897e4e161ce1517df7de1ae5042a65b6bcfd44401e0fc606559 |

| Crate | Version | License | Source |
|---|---|---|---|
| aho-corasick | 1.1.5 | Unlicense OR MIT | https://github.com/BurntSushi/aho-corasick |
| bitflags | 2.13.2 | MIT OR Apache-2.0 | https://github.com/bitflags/bitflags |
| cc | 1.2.67 | MIT OR Apache-2.0 | https://github.com/rust-lang/cc-rs |
| cfg-if | 1.0.5 | MIT OR Apache-2.0 | https://github.com/rust-lang/cfg-if |
| equivalent | 1.0.3 | Apache-2.0 OR MIT | https://github.com/indexmap-rs/equivalent |
| errno | 0.3.14 | MIT OR Apache-2.0 | https://github.com/lambda-fairy/rust-errno |
| filetime | 0.2.29 | MIT/Apache-2.0 | https://github.com/alexcrichton/filetime |
| find-msvc-tools | 0.1.14 | MIT OR Apache-2.0 | https://github.com/rust-lang/cc-rs |
| foldhash | 0.2.0 | Zlib | https://github.com/orlp/foldhash |
| hashbrown | 0.17.1 | MIT OR Apache-2.0 | https://github.com/rust-lang/hashbrown |
| indexmap | 2.14.2 | Apache-2.0 OR MIT | https://github.com/indexmap-rs/indexmap |
| itoa | 1.0.18 | MIT OR Apache-2.0 | https://github.com/dtolnay/itoa |
| memchr | 2.8.3 | Unlicense OR MIT | https://github.com/BurntSushi/memchr |
| proc-macro2 | 1.0.107 | MIT OR Apache-2.0 | https://github.com/dtolnay/proc-macro2 |
| quote | 1.0.47 | MIT OR Apache-2.0 | https://github.com/dtolnay/quote |
| regex | 1.13.1 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |
| regex-automata | 0.4.18 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |
| regex-syntax | 0.8.11 | MIT OR Apache-2.0 | https://github.com/rust-lang/regex |
| serde | 1.0.229 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |
| serde_core | 1.0.229 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |
| serde_derive | 1.0.229 | MIT OR Apache-2.0 | https://github.com/serde-rs/serde |
| serde_json | 1.0.154 | MIT OR Apache-2.0 | https://github.com/serde-rs/json |
| shlex | 2.0.1 | MIT OR Apache-2.0 | https://github.com/comex/rust-shlex |
| streaming-iterator | 0.1.9 | MIT OR Apache-2.0 | https://github.com/sfackler/streaming-iterator |
| syn | 3.0.9 | MIT OR Apache-2.0 | https://github.com/dtolnay/syn |
| tar | 0.4.46 | MIT OR Apache-2.0 | https://github.com/composefs/tar-rs |
| tree-sitter | 0.26.13 | MIT | https://github.com/tree-sitter/tree-sitter |
| tree-sitter-bash | 0.25.1 | MIT | https://github.com/tree-sitter/tree-sitter-bash |
| tree-sitter-batch | 0.11.1 | MIT | https://github.com/wharflab/tree-sitter-batch |
| tree-sitter-c-sharp | 0.23.5 | MIT | https://github.com/tree-sitter/tree-sitter-c-sharp |
| tree-sitter-css | 0.25.0 | MIT | https://github.com/tree-sitter/tree-sitter-css |
| tree-sitter-html | 0.23.2 | MIT | https://github.com/tree-sitter/tree-sitter-html |
| tree-sitter-javascript | 0.25.0 | MIT | https://github.com/tree-sitter/tree-sitter-javascript |
| tree-sitter-json | 0.24.8 | MIT | https://github.com/tree-sitter/tree-sitter-json |
| tree-sitter-language | 0.1.9 | MIT | https://github.com/tree-sitter/tree-sitter |
| tree-sitter-powershell | 0.26.4 | MIT | https://github.com/airbus-cert/tree-sitter-powershell |
| tree-sitter-python | 0.25.0 | MIT | https://github.com/tree-sitter/tree-sitter-python |
| tree-sitter-rust | 0.24.2 | MIT | https://github.com/tree-sitter/tree-sitter-rust |
| tree-sitter-sequel | 0.3.11 | MIT | https://github.com/derekstride/tree-sitter-sql.git |
| tree-sitter-toml-ng | 0.7.0 | MIT | https://github.com/tree-sitter-grammars/tree-sitter-toml |
| tree-sitter-typescript | 0.23.2 | MIT | https://github.com/tree-sitter/tree-sitter-typescript |
| tree-sitter-yaml | 0.7.2 | MIT | https://github.com/tree-sitter-grammars/tree-sitter-yaml |
| unicode-ident | 1.0.27 | (MIT OR Apache-2.0) AND Unicode-3.0 | https://github.com/dtolnay/unicode-ident |
| windows-link | 0.2.1 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |
| windows-sys | 0.61.2 | MIT OR Apache-2.0 | https://github.com/microsoft/windows-rs |
| zmij | 1.0.23 | MIT | https://github.com/dtolnay/zmij |
| libc | 0.2.190 | MIT OR Apache-2.0 | https://github.com/rust-lang/libc |
| linux-raw-sys | 0.12.1 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/sunfishcode/linux-raw-sys |
| rustix | 1.1.5 | Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | https://github.com/bytecodealliance/rustix |
| xattr | 1.6.1 | MIT OR Apache-2.0 | https://github.com/Stebalien/xattr |
