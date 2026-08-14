FROM python:3.13-slim

# uid 1000 matches the host owner of anything ever bind-mounted, the same
# convention as the calendar.
RUN useradd -u 1000 -m app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
