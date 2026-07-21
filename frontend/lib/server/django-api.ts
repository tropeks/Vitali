const DEFAULT_DOCKER_DJANGO_API_URL = "http://django:8000";
const DEFAULT_LOCAL_DJANGO_API_URL = "http://localhost:8000";

export function djangoApiBaseUrl(): string {
  const configured = process.env.DJANGO_API_URL?.trim();
  const baseUrl =
    configured ||
    (process.env.NODE_ENV === "development"
      ? DEFAULT_LOCAL_DJANGO_API_URL
      : DEFAULT_DOCKER_DJANGO_API_URL);

  return baseUrl.replace(/\/+$/, "");
}
