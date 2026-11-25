ALIASES = {
    "ACTGCG": "ActGCG",
}

def canonicalize_entity(name: str) -> str:
    return ALIASES.get(name, name)