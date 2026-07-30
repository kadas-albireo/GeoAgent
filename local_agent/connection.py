"""Back-compat shim: the ETH connection manager now ships inside ``geoagent``.

It moved to :mod:`geoagent.core.eth_cluster` so the plugin's provider dropdown can reach
it -- ``local_agent/`` is deliberately not importable by the shipped package or the
plugins, so tunnel logic living here could never be selected from the KADAS/QGIS UI.

This module only re-exports, so ``local_agent/tests/run_evals.py`` keeps working. New
code should import from :mod:`geoagent.core.eth_cluster` directly.

The eval runner's config still lives at ``local_agent/config.json``; pointing
``$GEOAGENT_ETH_CONFIG`` at it is what keeps the two in sync.
"""

from __future__ import annotations

from geoagent.core.eth_cluster import *  # noqa: F401,F403
from geoagent.core.eth_cluster import (  # noqa: F401
    ConnectionConfig,
    ConnectionError_,
    TunnelInfo,
    config_path,
    discover_node,
    doctor,
    down,
    ensure_tunnel,
    find_tunnel,
    geoagent_config,
    has_master,
    is_serving,
    list_models,
    load_config,
    main,
    save_config,
    start_tunnel,
    stop_tunnel,
    up,
)

if __name__ == "__main__":
    raise SystemExit(main())
