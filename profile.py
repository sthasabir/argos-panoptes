"""
Aayush's candidate profile — the ground truth both gates score against.
Sourced from MyResume2026.pdf + job_search_profile memory.
"""

CANDIDATE = {
    "name": "Aayush Shrestha",
    "grad_date": "2026-05",
    "level": "new_grad",           # entry-level / new grad, NOT senior
    "needs_sponsorship": True,      # H1B now/future — hard requirement
    "locations_ok": ["Remote", "US"],  # remote OK, open to US relocation
    "stack": [
        "Python", "TypeScript", "Java", "C++", "C", "JavaScript", "Kotlin", "SQL",
        "React", "Next.js", "FastAPI", "Node.js", "Three.js", "SwiftUI",
        "LangChain", "PyTorch", "Docker", "Git",
        "AWS", "GCP", "Vertex AI", "Google ADK", "Cloud Run",
        "PostgreSQL", "pgvector", "MySQL", "MongoDB", "Redis",
        "LLMs", "AI Agents", "RAG", "Gemini", "OpenAI API", "MCP", "Vertex AI Search",
    ],
    # role families in priority order (higher index in list = lower priority)
    "target_role_families": ["fullstack", "backend", "ai_ml", "swe"],
    "avoid_role_types": ["help_desk", "desktop_support", "manual_qa", "it_support", "sales"],
}

# Tsenta roleFamily / title → our normalized family
ROLE_FAMILY_MAP = {
    "SOFTWARE_ENGINEERING": "swe",
    "MACHINE_LEARNING": "ai_ml",
    "DATA_SCIENCE": "ai_ml",
    "AI": "ai_ml",
    "FRONTEND": "fullstack",
    "FULLSTACK": "fullstack",
    "FULL_STACK": "fullstack",
    "BACKEND": "backend",
    "DEVOPS": "backend",
    "PLATFORM": "backend",
}

ROLE_FAMILY_PRIORITY = {"fullstack": 0, "backend": 1, "ai_ml": 2, "swe": 3, "other": 9}
