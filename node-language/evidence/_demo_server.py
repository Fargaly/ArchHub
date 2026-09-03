import sys, time
sys.path.insert(0, ".")
from nodelang.application_server import ApplicationServer

server = ApplicationServer().start()
print("DEMO_URL", server.url, flush=True)
print("DEMO_BOOTSTRAP", server.bootstrap_url, flush=True)
try:
    while True:
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    server.close()
