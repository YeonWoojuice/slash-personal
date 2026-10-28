#!/usr/bin/env python3
"""Build a shell-free image and bind its rendered configuration to deployment inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
NAME_LABEL = "io.slash.prometheus.name"
HASH_LABEL = "io.slash.prometheus.config-sha256"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def render(name):
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,19}", name):
        raise ValueError("name must match the Terraform 3-20 character DNS name")
    template = (HERE / "config.json.tftpl").read_text()
    if template.count("${name}") != 1:
        raise ValueError("unexpected config template; review its renderer")
    rendered = template.replace("${name}", name)
    json.loads(rendered)  # JSON is also valid YAML for Prometheus.
    return rendered


def config_hash(name):
    return hashlib.sha256(render(name).encode()).hexdigest()


def arguments():
    return json.loads((HERE / "arguments.json").read_text())


def validate_metadata(info, name, actual_config):
    config = info["Config"]
    labels = config.get("Labels") or {}
    if info.get("Architecture") != "amd64" or info.get("Os") != "linux":
        raise ValueError("expected linux/amd64 image")
    if labels.get(NAME_LABEL) != name or labels.get(HASH_LABEL) != config_hash(name):
        raise ValueError("image name/config label does not match the deployment")
    if actual_config != render(name).encode():
        raise ValueError("image's config file differs from the shared template")
    if config.get("User") != "65532:65532":
        raise ValueError("unexpected runtime user")
    if config.get("Entrypoint") != ["/bin/prometheus"] or config.get("Cmd") != arguments():
        raise ValueError("image runtime arguments do not match the shared contract")


def inspect_image(image, name):
    info = json.loads(run("docker", "image", "inspect", image).stdout)[0]
    container = None
    try:
        container = run("docker", "create", "--pull=never", image).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="slash-prometheus-inspect-") as directory:
            path = Path(directory) / "prometheus.yml"
            run("docker", "cp", container + ":/etc/prometheus/prometheus.yml", str(path))
            validate_metadata(info, name, path.read_bytes())
    finally:
        if container:
            run("docker", "rm", "-v", container)
    return info


def build(name, image):
    with tempfile.TemporaryDirectory(prefix="slash-prometheus-context-") as directory:
        context = Path(directory)
        (context / "prometheus.yml").write_text(render(name))
        (context / "data").mkdir()
        (context / "data" / ".keep").touch()
        dockerfile = (HERE / "Dockerfile").read_text()
        dockerfile += "\nLABEL " + NAME_LABEL + "=" + json.dumps(name)
        dockerfile += " " + HASH_LABEL + "=" + json.dumps(config_hash(name)) + "\n"
        dockerfile += "CMD " + json.dumps(arguments()) + "\n"
        (context / "Dockerfile").write_text(dockerfile)
        # Only these generated, nonsecret files enter the build context.
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image,
                        str(context)], check=True)
    info = inspect_image(image, name)
    print(json.dumps({"image": image, "image_id": info["Id"], "name": name,
                      "config_sha256": config_hash(name)}))


def contract(name, image, output):
    if not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("use the published image's immutable repository@sha256 reference")
    info = inspect_image(image, name)
    if image not in info.get("RepoDigests", []):
        raise ValueError("the immutable reference is not attached to the inspected local image")
    result = {"prometheus_image_contract": {
        "image": image, "name": name, "config_sha256": config_hash(name)}}
    with Path(output).open("x") as file:
        json.dump(result, file, indent=2)
        file.write("\n")
    print("Verified image/config contract written to " + output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ["build", "contract"]:
        p = sub.add_parser(action)
        p.add_argument("--name", required=True)
        p.add_argument("--image", required=True)
        if action == "contract":
            p.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.action == "build":
            build(args.name, args.image)
        else:
            contract(args.name, args.image, args.output)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
