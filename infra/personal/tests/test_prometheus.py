"""Configuration binding and shell-free runtime boundaries for the Prometheus image."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "prometheus_image", REPO / "observability/personal/prometheus/image.py")
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


class PrometheusContract(unittest.TestCase):
    def metadata(self):
        return {"Architecture": "amd64", "Os": "linux", "Config": {
            "User": "65532:65532", "Entrypoint": ["/bin/prometheus"],
            "Cmd": image.arguments(), "Labels": {
                image.NAME_LABEL: "slash-lab", image.HASH_LABEL: image.config_hash("slash-lab")}}}

    def test_name_changes_dns_and_configuration_digest(self):
        one = json.loads(image.render("slash-lab"))
        other = json.loads(image.render("slash-ci"))
        self.assertEqual(one["scrape_configs"][0]["dns_sd_configs"][0]["names"],
                         ["core.slash-lab.internal"])
        self.assertEqual(other["scrape_configs"][0]["dns_sd_configs"][0]["names"],
                         ["core.slash-ci.internal"])
        self.assertNotEqual(image.config_hash("slash-lab"), image.config_hash("slash-ci"))

    def test_invalid_name_cannot_modify_configuration(self):
        for name in ["ab", "A-test", "a" * 21, "slash/../other", 'slash"', "slash\nother"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                image.render(name)

    def test_verified_metadata_matches_actual_file(self):
        image.validate_metadata(self.metadata(), "slash-lab", image.render("slash-lab").encode())

    def test_stale_image_or_forged_config_label_is_rejected(self):
        with self.assertRaises(ValueError):
            image.validate_metadata(self.metadata(), "slash-ci", image.render("slash-lab").encode())
        with self.assertRaises(ValueError):
            image.validate_metadata(self.metadata(), "slash-lab", image.render("slash-ci").encode())

    def test_root_shell_or_different_retention_is_rejected(self):
        for key, value in [("User", "0"), ("Entrypoint", ["/bin/sh"]),
                           ("Cmd", ["--web.listen-address=0.0.0.0:9090"])]:
            info = self.metadata()
            info["Config"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                image.validate_metadata(info, "slash-lab", image.render("slash-lab").encode())

    def test_terraform_uses_shared_inputs_and_checks_published_image(self):
        main = json.loads((REPO / "infra/personal/experiment/main.tf.json").read_text())
        prom = main["locals"]["monitoring_containers"][0]
        self.assertEqual(prom["entryPoint"], ["/bin/prometheus"])
        self.assertEqual(prom["user"], "65532:65532")
        self.assertNotIn("environment", prom)
        self.assertIn("arguments.json", prom["command"])
        self.assertIn("config.json.tftpl", main["locals"]["prometheus_config"])
        checks = main["resource"]["terraform_data"]["contract"]["lifecycle"]["precondition"]
        condition = next(c["condition"] for c in checks if "prometheus_image_contract" in c["condition"])
        for comparison in ["var.prometheus_image_contract.image == var.images.prometheus",
                           "var.prometheus_image_contract.name == var.name",
                           "var.prometheus_image_contract.config_sha256 == sha256(local.prometheus_config)"]:
            self.assertIn(comparison, condition)

    @unittest.skipUnless(shutil.which("terraform"), "Terraform executable required")
    def test_real_terraform_rejects_missing_or_mismatched_contract(self):
        main = json.loads((REPO / "infra/personal/experiment/main.tf.json").read_text())
        condition = next(c for c in main["resource"]["terraform_data"]["contract"]["lifecycle"]["precondition"]
                         if "prometheus_image_contract" in c["condition"])
        reference = "example.invalid/prometheus@sha256:" + "a" * 64
        expected = {"image": reference, "name": "slash-lab", "config_sha256": image.config_hash("slash-lab")}
        with tempfile.TemporaryDirectory(prefix="slash-prometheus-contract-") as directory:
            root = Path(directory)
            module = root / "infra/personal/experiment"
            module.mkdir(parents=True)
            template = root / "observability/personal/prometheus"
            template.mkdir(parents=True)
            shutil.copyfile(image.HERE / "config.json.tftpl", template / "config.json.tftpl")
            minimal = {
                "variable": {"name": {"default": "slash-lab"},
                             "images": {"default": {"prometheus": reference}},
                             "prometheus_image_contract": main["variable"]["prometheus_image_contract"]},
                "locals": {"monitoring_enabled": True,
                           "prometheus_config": main["locals"]["prometheus_config"]},
                "resource": {"terraform_data": {"contract": {
                    "lifecycle": {"precondition": [condition]}}}}}
            (module / "main.tf.json").write_text(json.dumps(minimal))
            subprocess.run(["terraform", "init", "-backend=false", "-input=false", "-no-color"],
                           cwd=module, capture_output=True, text=True, check=True)
            cases = [("correct", expected, True), ("missing", None, False)]
            for key, value in [("image", reference[:-1] + "b"), ("name", "slash-ci"),
                               ("config_sha256", "0" * 64)]:
                altered = dict(expected)
                altered[key] = value
                cases.append((key, altered, False))
            for name, contract, passes in cases:
                with self.subTest(name=name):
                    (module / "input.tfvars.json").write_text(json.dumps({"prometheus_image_contract": contract}))
                    result = subprocess.run(["terraform", "plan", "-refresh=false", "-input=false",
                                             "-no-color", "-var-file=input.tfvars.json"],
                                            cwd=module, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, passes, result.stdout + result.stderr)
                    if not passes:
                        self.assertIn("Generate a verified Prometheus image contract", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
