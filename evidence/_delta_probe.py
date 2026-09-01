import json, sys
sys.path.insert(0, ".")
import tests_replica.test_universal_interaction_server as T
from nodelang.application_server import ApplicationServer

server = ApplicationServer().start()
try:
    status, before = T._json(server, "/api/universal/canvas")
    node = next(n for n in before["nodes"] if n.get("openable"))
    # place from the catalogue the way the failing court does
    src = open("tests_replica/test_universal_interaction_server.py", encoding="utf-8").read()
    print("full projection bytes:", len(json.dumps(before)))
    print("top-level sizes in the FULL projection:")
    for k, v in sorted(before.items(), key=lambda kv: -len(json.dumps(kv[1])))[:10]:
        print("   %-28s %8d" % (k, len(json.dumps(v))))
finally:
    server.close()
