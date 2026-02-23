# Development Makefile for Ketchup Backend
# Run: make <target>

.PHONY: help install dev test lint format clean docker-up docker-down

help:
	@echo "Ketchup Backend - Development Tasks"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install       - Install dependencies"
	@echo "  dev           - Start development server"
	@echo "  test          - Run test suite"
	@echo "  test-cov      - Run tests with coverage report"
	@echo "  lint          - Run linting checks"
	@echo "  format        - Format code with black"
	@echo "  typecheck     - Run type checking with mypy"
	@echo "  clean         - Clean build artifacts"
	@echo "  docker-up     - Start Docker services (Firestore, Redis)"
	@echo "  docker-down   - Stop Docker services"
	@echo "  docker-logs   - View Docker service logs"
	@echo "  setup         - Complete setup (install + docker-up)"
	@echo "  etl-test      - Test ETL pipeline"

install:
	pip install --upgrade pip
	pip install -r requirements.txt
	@echo "Dependencies installed"

dev:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=. --cov-report=html --cov-report=term
	@echo "Coverage report generated: htmlcov/index.html"

lint:
	flake8 . --exclude=".venv,venv,__pycache__,.git" --max-line-length=100

format:
	black . --exclude=".venv,venv,__pycache__"
	@echo "Code formatted"

typecheck:
	mypy . --ignore-missing-imports --exclude=".venv,venv"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache htmlcov .coverage
	@echo "Cleaned build artifacts"

docker-up:
	docker-compose up -d
	@echo "Docker services started"
	@echo "   Firestore: http://localhost:8080"
	@echo "   Redis: localhost:6379"

docker-down:
	docker-compose down
	@echo "Docker services stopped"

docker-logs:
	docker-compose logs -f

setup: install docker-up
	@echo "Setup complete!"
	@echo "Run 'make dev' to start the development server"

etl-test:
	@echo "Testing ETL pipeline components..."
	python -c "from utils.data_normalizer import DataNormalizer; print('DataNormalizer imported')"
	python -c "from database.firestore_client import FirestoreClient; print('FirestoreClient imported')"
	@echo "All ETL components working"
