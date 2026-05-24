from .best_buy import BestBuy
from .target import Target
from .pokemon_center import PokemonCenter, PokemonCenterSitemap
from .walmart import Walmart

# Maps the "retailer" field in config.json to the right class
RETAILER_MAP = {
    "best_buy": BestBuy,
    "target": Target,
    "pokemon_center": PokemonCenter,
    "pokemon_center_sitemap": PokemonCenterSitemap,
    "walmart": Walmart,
}
