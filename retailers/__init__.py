from .best_buy import BestBuy
from .target import Target
from .pokemon_center import PokemonCenter, PokemonCenterSitemap
from .walmart import Walmart
from .premium_bandai import PremiumBandai, PremiumBandaiSeries
from .square_enix import SquareEnix

# Maps the "retailer" field in config.json to the right class
RETAILER_MAP = {
    "best_buy": BestBuy,
    "target": Target,
    "pokemon_center": PokemonCenter,
    "pokemon_center_sitemap": PokemonCenterSitemap,
    "walmart": Walmart,
    "premium_bandai": PremiumBandai,
    "premium_bandai_series": PremiumBandaiSeries,
    "square_enix": SquareEnix,
}
