"""agent-memes: meme video clips for AI agents and any editing workflow."""

__version__ = "0.1.0"

__all__ = ["MemeKit", "MemeError", "__version__"]


def __getattr__(name):  # lazy imports keep `import agent_memes` cheap
    if name == "MemeKit":
        from .kit import MemeKit

        return MemeKit
    if name == "MemeError":
        from .errors import MemeError

        return MemeError
    raise AttributeError(name)
