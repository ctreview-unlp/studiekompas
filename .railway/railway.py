from railway_sdk import define_railway, github, preserve, project, service
# This repository manages only its own resources in the environment. Other
# repositories export their own partial name.
# See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
PARTIAL = "studiekompas"
# Both services run the same code; start.sh picks the role from SERVICE_ROLE.
@define_railway
def main(ctx=None):
    studiekompas = service(
        "studiekompas",
        source=github("ctreview-unlp/studiekompas", branch="main", checkSuites=False),
        start="bash start.sh",
        replicas={ "europe-west4-drams3a": 1 },
        env={ "ADMIN_PASSWORD": preserve(), "ANTHROPIC_API_KEY": preserve(), "APP_ENV": preserve(), "DATABASE_URL": preserve(), "VOYAGE_API_KEY": preserve() },
    )
    scraper = service(
        "studiekompas-scraper",
        source=github("ctreview-unlp/studiekompas", branch="main", checkSuites=False),
        start="bash start.sh",
        replicas={ "europe-west4-drams3a": 1 },
        deploy={ "cronSchedule": "0 3 * * *", "restartPolicyType": "NEVER" },
        env={ "DATABASE_URL": preserve(), "SERVICE_ROLE": preserve(), "VOYAGE_API_KEY": preserve() },
    )
    return project("UNLP chatbot", variables={"managed": True}, resources=[studiekompas, scraper])
