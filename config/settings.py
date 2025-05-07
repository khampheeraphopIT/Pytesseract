from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ELASTICSEARCH_HOSTS: str = "http://localhost:9200"
    ELASTICSEARCH_USERNAME: str = "elastic"
    ELASTICSEARCH_PASSWORD: str
    ELASTICSEARCH_INDEX: str = "documents"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()