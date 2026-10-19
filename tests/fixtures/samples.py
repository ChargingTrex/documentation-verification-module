"""
The hand-checked reference set the engine is measured against.

Each sample states, alongside its text, the values a human read off it:
years of experience and education level. The Phase 2 checkpoint is that the
engine reproduces those numbers, and that the two backend-relevant resumes
outrank the three irrelevant ones against SAMPLE_JOB_DESCRIPTION.

Text lives here rather than in binary fixtures so the expected values sit
next to the words they come from. `manage.py make_sample_resumes` renders
these into real PDF and DOCX files for the file-parsing path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SampleResume:
    key: str
    filename: str
    lines: tuple[str, ...]
    #: Hand-checked: total years of experience a human reads off this resume.
    expected_experience_years: float
    #: Hand-checked: education levels literally named in the text.
    expected_education_levels: frozenset[str]
    #: Whether this resume is relevant to SAMPLE_JOB_DESCRIPTION.
    relevant: bool

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def format(self) -> str:
        return self.filename.rsplit(".", 1)[-1]


SAMPLE_JOB_DESCRIPTION = """
Backend Engineer — Placement Drive 2026

We are hiring a backend engineer to build and maintain REST APIs for our
logistics platform. You will design database schemas, write Django views and
serializers, tune PostgreSQL queries, and run background jobs with Celery.

Required:
- 2+ years of professional experience writing backend services in Python
- Strong Django and Django REST Framework knowledge
- Relational database design and SQL query optimisation, ideally PostgreSQL
- Comfortable with Git, Docker and continuous integration
- A bachelor's degree in computer science, engineering or a related field

Nice to have: Celery or similar task queues, AWS deployment experience,
writing unit and integration tests.
""".strip()


SAMPLE_RESUMES: tuple[SampleResume, ...] = (
    SampleResume(
        key="backend_engineer",
        filename="aarav_mehta_backend.pdf",
        lines=(
            "Aarav Mehta",
            "aarav.mehta@college.edu | PRN2022CS001",
            "",
            "SUMMARY",
            "Backend engineer with 3 years of professional experience building REST",
            "APIs in Python and Django. Comfortable owning database design,",
            "query optimisation and background job processing end to end.",
            "",
            "EDUCATION",
            "B.Tech in Computer Engineering, 2026",
            "",
            "EXPERIENCE",
            "Backend Developer, Loadstar Logistics",
            "Built Django REST Framework APIs backing a fleet tracking product.",
            "Designed PostgreSQL schemas and tuned slow queries with EXPLAIN ANALYZE.",
            "Moved nightly reporting onto Celery workers running in Docker.",
            "",
            "SKILLS",
            "Python, Django, Django REST Framework, PostgreSQL, SQL, Celery,",
            "Docker, Git, pytest, continuous integration, AWS",
        ),
        expected_experience_years=3.0,
        expected_education_levels=frozenset({"UG"}),
        relevant=True,
    ),
    SampleResume(
        key="data_engineer",
        filename="sana_qureshi_data.docx",
        lines=(
            "Sana Qureshi",
            "sana.qureshi@college.edu | PRN2022IT004",
            "",
            "SUMMARY",
            "Data engineer with 2 years 6 months of experience writing Python",
            "services and SQL pipelines. Built and maintained ETL jobs moving data",
            "into PostgreSQL for downstream reporting.",
            "",
            "EDUCATION",
            "M.Tech in Data Science, 2026",
            "",
            "EXPERIENCE",
            "Data Engineer, Nimbus Analytics",
            "Wrote Python ETL pipelines orchestrated with Airflow.",
            "Modelled PostgreSQL warehouse tables and optimised reporting queries.",
            "Packaged jobs in Docker and shipped them through a CI pipeline.",
            "",
            "SKILLS",
            "Python, SQL, PostgreSQL, Airflow, pandas, ETL, Docker, Git, Django ORM",
        ),
        expected_experience_years=2.5,
        expected_education_levels=frozenset({"Masters"}),
        relevant=True,
    ),
    SampleResume(
        key="frontend_intern",
        filename="kabir_nair_frontend.pdf",
        lines=(
            "Kabir Nair",
            "kabir.nair@college.edu | PRN2022IT005",
            "",
            "SUMMARY",
            "Front-end focused developer with 6 months of internship experience",
            "building marketing pages and design-system components.",
            "",
            "EDUCATION",
            "Pursuing BCA, expected 2027",
            "",
            "EXPERIENCE",
            "Front-end Intern, Bright Studio",
            "Built responsive landing pages in React and Tailwind CSS.",
            "Translated Figma designs into reusable components.",
            "",
            "SKILLS",
            "React, TypeScript, HTML, CSS, Tailwind, Figma, accessibility",
        ),
        expected_experience_years=0.5,
        expected_education_levels=frozenset({"UG"}),
        relevant=False,
    ),
    SampleResume(
        key="mechanical_designer",
        filename="arjun_deshmukh_mechanical.docx",
        lines=(
            "Arjun Deshmukh",
            "arjun.deshmukh@college.edu | PRN2022ME009",
            "",
            "SUMMARY",
            "Mechanical design engineer with 4 years of experience in sheet metal",
            "and injection-moulded part design for automotive assemblies.",
            "",
            "EDUCATION",
            "B.E. in Mechanical Engineering, 2026",
            "",
            "EXPERIENCE",
            "Design Engineer, Pinnacle Auto Components",
            "Produced 3D models and manufacturing drawings in SolidWorks.",
            "Ran thermal and stress simulations on bracket assemblies.",
            "Applied GD&T to drawings and led design reviews with suppliers.",
            "",
            "SKILLS",
            "SolidWorks, AutoCAD, CATIA, GD&T, FEA, sheet metal design, ANSYS",
        ),
        expected_experience_years=4.0,
        expected_education_levels=frozenset({"UG"}),
        relevant=False,
    ),
    SampleResume(
        key="marketing_executive",
        filename="ishita_banerjee_marketing.pdf",
        lines=(
            "Ishita Banerjee",
            "ishita.banerjee@college.edu | PRN2022ME010",
            "",
            "SUMMARY",
            "Marketing executive with 1 year of experience running content and",
            "social campaigns for consumer brands.",
            "",
            "EDUCATION",
            "BBA in Marketing, 2026",
            "",
            "EXPERIENCE",
            "Marketing Executive, Hearth & Co.",
            "Planned editorial calendars and wrote long-form blog content.",
            "Ran paid social campaigns and reported on channel performance.",
            "",
            "SKILLS",
            "Content marketing, SEO, copywriting, Google Analytics, Canva,",
            "email campaigns, social media strategy",
        ),
        expected_experience_years=1.0,
        expected_education_levels=frozenset({"UG"}),
        relevant=False,
    ),
)

SAMPLES_BY_KEY = {sample.key: sample for sample in SAMPLE_RESUMES}
RELEVANT_KEYS = frozenset(s.key for s in SAMPLE_RESUMES if s.relevant)
