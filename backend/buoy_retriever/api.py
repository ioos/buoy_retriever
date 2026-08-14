from datasets.api import dataset_router, config_router
from ninja import NinjaAPI, Router
from pipelines.api import router as pipelines_router

from ninja_postgrest import build_router as build_postgrest_router

api = NinjaAPI(docs_url="/docs/")

api.add_router("/configs/", config_router)
api.add_router("/datasets/", dataset_router)
api.add_router("/pipelines/", pipelines_router)
api.add_router(
    "/pg/",
    build_postgrest_router(router=Router(tags=["PostgREST-compatible endpoints"])),
)
