"""Serve the REALITY-graded grand map on the canvas: every domain %% is a live
average of probes on real artifacts; nodes with no evidence read 0 (unproven)."""
from .core import Store, validate_store
from . import map_import
from .serve_canvas import CanvasServer


def reality_server(port=8479):
    s = Store()
    reg = map_import.import_grand_map_reality(s)
    validate_store(s)
    return CanvasServer(s, reg['session'], reg=None, port=port)


if __name__ == '__main__':
    srv = reality_server().start()
    print('REALITY canvas at', srv.url, '|', len(srv.store.nodes), 'nodes')
    import time
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
