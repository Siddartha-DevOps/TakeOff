"from fastapi import APIRouter
from typing import List

router = APIRouter(prefix=\"/blogs\", tags=[\"Blog\"])

# Mock blog data
MOCK_BLOGS = [
    {
        \"id\": 1,
        \"title\": \"5 Ways AI is Transforming Construction Takeoffs in 2026\",
        \"excerpt\": \"Discover how artificial intelligence is revolutionizing the estimating process, reducing takeoff time by 85% and improving accuracy to 98%.\",
        \"content\": \"Full blog content here...\",
        \"author_name\": \"Sarah Chen\",
        \"author_role\": \"Senior Estimator\",
        \"author_company\": \"TakeOff.ai\",
        \"created_at\": \"2026-03-15T10:00:00Z\",
        \"tags\": [\"AI\", \"Construction\", \"Takeoffs\"],
        \"read_time\": \"6 min read\"
    },
    {
        \"id\": 2,
        \"title\": \"From Manual to Automated: A Case Study in Construction Efficiency\",
        \"excerpt\": \"How BuildRight LLC reduced their estimating workload from 40 hours to 6 hours per project using TakeOff.ai's AI-powered detection.\",
        \"content\": \"Full blog content here...\",
        \"author_name\": \"Michael Torres\",
        \"author_role\": \"Project Manager\",
        \"author_company\": \"BuildRight LLC\",
        \"created_at\": \"2026-03-10T14:30:00Z\",
        \"tags\": [\"Case Study\", \"Efficiency\", \"ROI\"],
        \"read_time\": \"8 min read\"
    },
    {
        \"id\": 3,
        \"title\": \"Understanding Blueprint AI: Doors, Windows, and Room Detection Explained\",
        \"excerpt\": \"A technical deep-dive into how computer vision models detect architectural elements in construction drawings with 98% accuracy.\",
        \"content\": \"Full blog content here...\",
        \"author_name\": \"Dr. Priya Patel\",
        \"author_role\": \"AI Research Lead\",
        \"author_company\": \"TakeOff.ai\",
        \"created_at\": \"2026-03-05T09:00:00Z\",
        \"tags\": [\"AI\", \"Technical\", \"Computer Vision\"],
        \"read_time\": \"10 min read\"
    },
    {
        \"id\": 4,
        \"title\": \"The Future of Construction Estimating: Trends to Watch in 2026\",
        \"excerpt\": \"From AI-powered takeoffs to real-time collaboration, explore the innovations reshaping how estimators work.\",
        \"content\": \"Full blog content here...\",
        \"author_name\": \"James Anderson\",
        \"author_role\": \"Industry Analyst\",
        \"author_company\": \"Construction Tech Review\",
        \"created_at\": \"2026-02-28T11:00:00Z\",
        \"tags\": [\"Trends\", \"Future\", \"Industry\"],
        \"read_time\": \"7 min read\"
    },
    {
        \"id\": 5,
        \"title\": \"Best Practices for Digital Takeoff Workflows\",
        \"excerpt\": \"Expert tips for streamlining your digital takeoff process and maximizing ROI from construction technology investments.\",
        \"content\": \"Full blog content here...\",
        \"author_name\": \"Lisa Martinez\",
        \"author_role\": \"Chief Estimator\",
        \"author_company\": \"ACME Construction\",
        \"created_at\": \"2026-02-20T13:00:00Z\",
        \"tags\": [\"Best Practices\", \"Workflow\", \"Tips\"],
        \"read_time\": \"5 min read\"
    },
    {
        \"id\": 6,
        \"title\": \"ROI Calculator: How Much Can You Save with Automated Takeoffs?\",
        \"excerpt\": \"Calculate your potential savings and payback period when switching from manual to AI-powered construction takeoffs.\",
        \"content\": \"Full blog content here...\",
        \"author_name\": \"Robert Kim\",
        \"author_role\": \"Financial Analyst\",
        \"author_company\": \"TakeOff.ai\",
        \"created_at\": \"2026-02-15T10:00:00Z\",
        \"tags\": [\"ROI\", \"Savings\", \"Business\"],
        \"read_time\": \"4 min read\"
    }
]

@router.get(\"\")
async def list_blogs():
    \"\"\"Public endpoint - no authentication required\"\"\"
    return MOCK_BLOGS

@router.get(\"/{blog_id}\")
async def get_blog(blog_id: int):
    \"\"\"Get single blog post\"\"\"
    blog = next((b for b in MOCK_BLOGS if b[\"id\"] == blog_id), None)
    if not blog:
        return {\"error\": \"Blog not found\"}
    return blog
"