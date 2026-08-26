from .best_buy import BestBuy, BestBuySearch
from .pokemon_center import PokemonCenter, PokemonCenterSitemap, PokemonCenterCategory
from .premium_bandai import PremiumBandai, PremiumBandaiSeries
from .plaza_japan import PlazaJapan
from .amazon import Amazon

# Maps the "retailer" field in config.json to the right class
RETAILER_MAP = {
    "best_buy": BestBuy,
    "best_buy_search": BestBuySearch,
    "pokemon_center": PokemonCenter,
    "pokemon_center_sitemap": PokemonCenterSitemap,
    "pokemon_center_category": PokemonCenterCategory,
    "premium_bandai": PremiumBandai,
    "premium_bandai_series": PremiumBandaiSeries,
    "plaza_japan": PlazaJapan,
    "amazon": Amazon,
}
