import os
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allow the grader's browser page to call this API from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Layer 1: Defaults (hardcoded, lowest precedence)
# ---------------------------------------------------------------------------
DEFAULTS = {
    "port": 8000,
    "workers": 1,
    "debug": False,
    "log_level": "info",
    "api_key": "default-secret-000",
}

# Keys that come in as SOME_ENV_NAME need to be translated to our nice
# lowercase config names. NUM_WORKERS is a special alias -> workers.
ALIAS_MAP = {
    "NUM_WORKERS": "workers",
}


def map_env_key(raw_key: str):
    """Turn an env-style key like APP_PORT or NUM_WORKERS into a config key
    like 'port' or 'workers'. Returns None if the key isn't relevant."""
    if raw_key in ALIAS_MAP:
        return ALIAS_MAP[raw_key]
    if raw_key.startswith("APP_"):
        return raw_key[len("APP_"):].lower()
    return None


# ---------------------------------------------------------------------------
# Layer 2: config.<env>.yaml
# ---------------------------------------------------------------------------
def load_yaml_layer(env_name: str = "development"):
    path = BASE_DIR / f"config.{env_name}.yaml"
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return {str(k): v for k, v in data.items()}
    return {}


# ---------------------------------------------------------------------------
# Layer 3: .env file (parsed manually, no external lib needed)
# ---------------------------------------------------------------------------
def load_dotenv_layer():
    layer = {}
    path = BASE_DIR / ".env"
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                raw_key, value = line.split("=", 1)
                mapped = map_env_key(raw_key.strip())
                if mapped:
                    layer[mapped] = value.strip()
    return layer


# ---------------------------------------------------------------------------
# Layer 4: real OS environment variables (APP_* prefix)
# ---------------------------------------------------------------------------
def load_os_env_layer():
    layer = {}
    for raw_key, value in os.environ.items():
        mapped = map_env_key(raw_key)
        if mapped:
            layer[mapped] = value
    return layer


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------
def coerce(key: str, value):
    if key in ("port", "workers"):
        return int(value)
    if key == "debug":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    return str(value)


@app.get("/effective-config")
def effective_config(request: Request):
    # Merge low -> high precedence
    merged = dict(DEFAULTS)
    merged.update(load_yaml_layer("development"))
    merged.update(load_dotenv_layer())
    merged.update(load_os_env_layer())

    # Layer 5: CLI overrides via repeated ?set=key=value query params
    for item in request.query_params.getlist("set"):
        if "=" in item:
            k, v = item.split("=", 1)
            merged[k.strip()] = v.strip()

    # Coerce every value to its correct type
    result = {k: coerce(k, v) for k, v in merged.items()}

    # Always mask the secret, no matter which layer it came from
    result["api_key"] = "****"

    # Return the 5 required keys in a stable order
    return {
        "port": result.get("port", DEFAULTS["port"]),
        "workers": result.get("workers", DEFAULTS["workers"]),
        "debug": result.get("debug", DEFAULTS["debug"]),
        "log_level": result.get("log_level", DEFAULTS["log_level"]),
        "api_key": "****",
    }
