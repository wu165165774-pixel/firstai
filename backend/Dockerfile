FROM python:3.12-slim


WORKDIR /app


COPY pyproject.toml .


RUN pip install --upgrade pip


RUN pip install fastapi uvicorn pydantic pydantic-settings python-dotenv loguru


COPY . .


EXPOSE 8000


CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]