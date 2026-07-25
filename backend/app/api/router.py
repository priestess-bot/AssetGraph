from fastapi import APIRouter

from app.api.routes import (
    compatibility,
    content_projects,
    data_governance,
    functional_live_rooms,
    functional_videos,
    functional_operations,
    functional_learning,
    functional_knowledge,
    assets,
    broadcast_schedules,
    console,
    control_plane,
    digital_humans,
    live_observations,
    lives,
    maitu,
    maitu_workbench,
    policy,
    products,
    rag,
    releases,
    scripts,
    video_productions,
    video_segments,
    voice_profiles,
)

api_router = APIRouter()
api_router.include_router(compatibility.router)
api_router.include_router(console.router)
api_router.include_router(control_plane.router)
api_router.include_router(policy.router)
api_router.include_router(assets.router)
api_router.include_router(broadcast_schedules.router)
api_router.include_router(content_projects.router)
api_router.include_router(data_governance.router)
api_router.include_router(functional_live_rooms.router)
api_router.include_router(functional_videos.router)
api_router.include_router(functional_operations.router)
api_router.include_router(functional_learning.router)
api_router.include_router(functional_knowledge.router)
api_router.include_router(lives.router)
api_router.include_router(digital_humans.router)
api_router.include_router(voice_profiles.router)
api_router.include_router(products.router)
api_router.include_router(scripts.router)
api_router.include_router(video_segments.router)
api_router.include_router(video_productions.router)
api_router.include_router(maitu.router)
api_router.include_router(maitu_workbench.router)
api_router.include_router(live_observations.router)
api_router.include_router(rag.router)
api_router.include_router(releases.router)
