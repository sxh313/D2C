"""File contract for the optional local React project adapter."""
import re


def normalize_project_source(path: str, content: str) -> str:
    """Resolve image URLs for nested previews before recording file hashes."""
    if path.endswith((".tsx", ".jsx", ".ts", ".js")):
        return re.sub(r"([\"'(\s])/images/", r"\1./images/", content)
    if path.endswith(".css"):
        return re.sub(r"(url\(\s*[\"']?)\./images/", r"\1/images/", content, flags=re.IGNORECASE)
    return content


def is_project_file(path: str) -> bool:
    # The trusted template owns the entrypoint, dependencies and build config.
    return (bool(re.fullmatch(r"src/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.(?:tsx|ts|jsx|js|css)", path))
            and path not in {"src/main.tsx", "src/tailwind.css"}
            and not any(part.startswith(".") or part.casefold() in {"node_modules", "dist", ".git"}
                        for part in path.split("/")))
