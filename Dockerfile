# Start from an official, lightweight Python base image
FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

# Copy dependency list and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the python script into the container
COPY secretary.py .

# Run the python script when the container launches (-u prevents output buffering)
CMD ["python", "-u", "secretary.py"]
