#!/usr/bin/env python3
"""Exercise the built image on an internal Docker network without AWS or host ports."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from urllib.parse import urlencode

from image import config_hash, inspect_image, run

HELPER = "python:3.12-alpine"  # Local test fixture only; never part of the product image.
SERVER = '''from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/actuator/prometheus":
            self.send_error(404)
            return
        body = b"# TYPE slash_fixture_value gauge\\nslash_fixture_value 42\\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
HTTPServer(("0.0.0.0", 9091), Handler).serve_forever()
'''


def verify(image, name):
    info = inspect_image(image, name)
    result = {"at": datetime.now(timezone.utc).isoformat(), "image": image,
              "image_id": info["Id"], "name": name, "platform": "linux/amd64",
              "config_sha256": config_hash(name), "checks": {},
              "aws_calls": False, "host_ports_published": False}
    checks = result["checks"]
    prefix = "slash-prometheus-" + secrets.token_hex(5)
    network, target, prom, probe = [prefix + "-" + suffix
                                    for suffix in ["net", "target", "prom", "probe"]]
    containers = []
    network_created = False
    try:
        checked = run("docker", "run", "--rm", "--network", "none", "--entrypoint",
                      "/bin/promtool", image, "check", "config", "/etc/prometheus/prometheus.yml")
        checks["promtool_config"] = "SUCCESS" in checked.stdout + checked.stderr
        if not checks["promtool_config"]:
            raise AssertionError("promtool did not confirm the config")
        version = run("docker", "run", "--rm", "--network", "none", image, "--version")
        result["prometheus_version"] = (version.stdout + version.stderr).splitlines()[0]
        if "version 3.15.0" not in result["prometheus_version"]:
            raise AssertionError("Prometheus version changed")
        checks["prometheus_version_unchanged"] = True
        subprocess.run(["docker", "pull", HELPER], check=True, capture_output=True)
        run("docker", "network", "create", "--internal", network)
        network_created = True
        containers.append(target)
        run("docker", "run", "-d", "--name", target, "--network", network,
            "--network-alias", "core." + name + ".internal", HELPER,
            "python", "-u", "-c", SERVER)
        containers.append(prom)
        run("docker", "run", "-d", "--name", prom, "--network", network,
            "--cap-drop=ALL", "--security-opt=no-new-privileges", image)
        containers.append(probe)
        run("docker", "run", "-d", "--name", probe, "--network", "container:" + prom,
            HELPER, "python", "-c", "import time; time.sleep(600)")

        def api(path, parameters=None):
            url = "http://127.0.0.1:9090" + path
            if parameters:
                url += "?" + urlencode(parameters)
            code = ("import urllib.request; "
                    "print(urllib.request.urlopen(" + repr(url) + ", timeout=2).read().decode())")
            return run("docker", "exec", probe, "python", "-c", code).stdout

        def wait_for(operation, accept, seconds=65):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    value = operation()
                    if accept(value):
                        return value
                except (subprocess.CalledProcessError, ValueError, KeyError):
                    pass
                time.sleep(1)
            raise AssertionError("Prometheus did not reach the expected state within the limit")

        wait_for(lambda: api("/-/ready"), lambda text: "Ready" in text, seconds=35)
        checks["ready"] = True
        targets = wait_for(lambda: json.loads(api("/api/v1/targets")),
                           lambda d: any(t["health"] == "up" for t in d["data"]["activeTargets"]))
        active = targets["data"]["activeTargets"]
        if len(active) != 1 or active[0]["labels"]["job"] != "slash-api-personal":
            raise AssertionError("unexpected scrape target")
        if not active[0]["scrapeUrl"].endswith(":9091/actuator/prometheus"):
            raise AssertionError("unexpected metrics port/path")
        checks["dns_discovery_and_scrape"] = True
        sample = json.loads(api("/api/v1/query", {"query": "slash_fixture_value"}))["data"]["result"]
        if len(sample) != 1 or sample[0]["value"][1] != "42":
            raise AssertionError("synthetic metric not stored")
        historical_time = sample[0]["value"][0]
        checks["metric_value"] = True
        flags = json.loads(api("/api/v1/status/flags"))["data"]
        if flags["web.listen-address"] != "127.0.0.1:9090":
            raise AssertionError("unexpected listen address")
        if flags["storage.tsdb.retention.time"] != "6h" or flags["storage.tsdb.retention.size"] != "2GiB":
            raise AssertionError("unexpected retention flags: " + str({k:v for k,v in flags.items() if 'retention' in k}))
        checks["retention_6h_2GB"] = True
        container = json.loads(run("docker", "inspect", prom).stdout)[0]
        if container["HostConfig"].get("PortBindings"):
            raise AssertionError("test published a host port")
        prom_ip = container["NetworkSettings"]["Networks"][network]["IPAddress"]
        deny_code = ("import socket\ns=socket.socket(); s.settimeout(2)\n"
                     "result=s.connect_ex((" + repr(prom_ip) + ",9090)); s.close()\n"
                     "assert result != 0, 'Prometheus reachable outside loopback'\n")
        run("docker", "exec", target, "python", "-c", deny_code)
        checks["loopback_only"] = True
        processes = run("docker", "top", prom, "-eo", "pid,uid,gid,args").stdout.splitlines()[1:]
        if not processes or any(line.split()[1:3] != ["65532", "65532"] for line in processes):
            raise AssertionError("unexpected process user: " + str(processes))
        checks["nonroot_uid_gid_65532"] = True
        for path in ["/bin/sh", "/bin/bash", "/bin/busybox", "/bin/base64", "/usr/bin/base64"]:
            absent = subprocess.run(["docker", "exec", prom, path, "--help"],
                                    capture_output=True, text=True)
            if absent.returncode == 0 or not any(message in absent.stderr + absent.stdout
                                                for message in ["no such file", "not found"]):
                raise AssertionError("expected executable absent: " + path)
        checks["no_shell_busybox_base64"] = True
        with tempfile.TemporaryDirectory(prefix="slash-prometheus-wal-") as directory:
            run("docker", "cp", prom + ":/prometheus/wal", directory)
            if not any(p.stat().st_size > 0 for p in Path(directory).rglob("*") if p.is_file()):
                raise AssertionError("TSDB WAL is empty")
        checks["tsdb_wal_written"] = True
        run("docker", "stop", "--time", "10", target)
        run("docker", "stop", "--time", "20", prom)
        # Recreate the observer because it shares the old container network namespace.
        run("docker", "rm", "-f", probe)
        run("docker", "start", prom)
        run("docker", "run", "-d", "--name", probe, "--network", "container:" + prom,
            HELPER, "python", "-c", "import time; time.sleep(600)")
        wait_for(lambda: api("/-/ready"), lambda text: "Ready" in text, seconds=35)
        restored = json.loads(api("/api/v1/query", {"query": "slash_fixture_value", "time": historical_time}))["data"]["result"]
        if len(restored) != 1 or restored[0]["value"][1] != "42":
            raise AssertionError("historical metric did not survive restart without the target")
        checks["tsdb_read_after_restart_without_target"] = True
        result["status"] = "PASS"
        return result
    finally:
        failures = []
        for container in reversed(containers):
            removed = subprocess.run(["docker", "rm", "-fv", container], capture_output=True, text=True)
            if removed.returncode and "No such container" not in removed.stderr:
                failures.append(container)
        if network_created:
            removed = subprocess.run(["docker", "network", "rm", network], capture_output=True, text=True)
            if removed.returncode:
                failures.append(network)
        result["cleanup"] = "completed" if not failures else {"failed": failures}
        if failures:
            raise RuntimeError("test resource cleanup failed: " + ", ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--result")
    args = parser.parse_args()
    result = verify(args.image, args.name)
    result["limits"] = ["Internal local fixture only; no ECS, Cloud Map or AWS validation.",
                       "Restart reuses the same container filesystem; ECS task replacement is not persistent storage.",
                       "No ECR security scan is performed by this test."]
    if args.result:
        with Path(args.result).open("x") as file:
            json.dump(result, file, indent=2)
            file.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
