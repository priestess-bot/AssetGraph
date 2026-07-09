from fastapi import APIRouter

from app.api.routes import assets, digital_humans, lives, maitu, products, rag, scripts, video_segments, voice_profiles

api_router = APIRouter()
api_router.include_router(assets.router)
api_router.include_router(lives.router)
api_router.include_router(digital_humans.router)
api_router.include_router(voice_profiles.router)
api_router.include_router(products.router)
api_router.include_router(scripts.router)
api_router.include_router(video_segments.router)
api_router.include_router(maitu.router)
api_router.include_router(rag.router)
