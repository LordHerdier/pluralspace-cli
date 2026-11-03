(import (
  let
    lock = builtins.fromJSON (builtins.readFile ./flake.lock);
    node = lock.nodes.${lock.nodes.root.inputs.flake-compat};
  in
  fetchTarball {
    url = node.locked.url or "https://github.com/edolstra/flake-compat/archive/${node.locked.rev}.tar.gz";
    sha256 = node.locked.narHash;
  }
) { src = ./.; }).shellNix
