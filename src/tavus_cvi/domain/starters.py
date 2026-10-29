"""Normalize scraped scaffolding without providing any solution logic."""


def runnable_starter(language: str, source: str) -> str:
    if language != "python3":
        return source
    lines = source.rstrip().splitlines()
    if lines and lines[-1].rstrip().endswith(":"):
        indent = len(lines[-1]) - len(lines[-1].lstrip()) + 4
        return "\n".join(lines) + "\n" + " " * indent + "pass\n"
    return source
