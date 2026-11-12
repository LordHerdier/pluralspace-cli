{
  # Dev shell for tools/record_fixtures.py. Kept out of the main flake so
  # `nix flake check` and CI never download a browser.
  #   nix develop ./tools
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.pass
            (pkgs.python3.withPackages (ps: [
              ps.playwright
              ps.pytest
            ]))
          ];
          env = {
            # nixpkgs' pinned browsers; `playwright install` can't run on NixOS
            PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
            PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
          };
        };
      });
    };
}
