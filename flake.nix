{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    flake-compat = {
      url = "github:edolstra/flake-compat";
      flake = false;
    };
  };

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-darwin"
        "x86_64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        pluralspace = pkgs.python3Packages.buildPythonApplication {
          pname = "pluralspace-cli";
          version = "0.0.1";
          pyproject = true;
          src = ./.;

          build-system = [ pkgs.python3Packages.setuptools ];
          nativeCheckInputs = [ pkgs.python3Packages.pytestCheckHook ];

          # credentials are read from pass at runtime
          makeWrapperArgs = [
            "--prefix"
            "PATH"
            ":"
            (pkgs.lib.makeBinPath [ pkgs.pass ])
          ];

          meta.mainProgram = "plsp";
          meta.license = pkgs.lib.licenses.gpl3Plus;
        };
        default = pluralspace;
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.pass
            (pkgs.python3.withPackages (ps: [ ps.pytest ]))
          ];
          env.PYTHONPATH = "src";
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt-rfc-style);
    };
}
