.PHONY: install install-dev test lint format run clean help

# Default target
help:
	@echo "Illuminate CI - Available Commands"
	@echo ""
	@echo "  make install      Install production dependencies"
	@echo "  make install-dev  Install dev dependencies (includes test tools)"
	@echo "  make test         Run all tests"
	@echo "  make lint         Check code quality"
	@echo "  make format       Format code"
	@echo "  make run          Start backend and frontend"
	@echo "  make clean        Remove generated files"
	@echo ""

# Install production dependencies
install:
	python -m venv venv
	. venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

# Install development dependencies
install-dev: install
	. venv/bin/activate && pip install -r requirements-dev.txt
	cd frontend && npm install

# Run all tests
test:
	. venv/bin/activate && pytest tests/ -v
	cd frontend && npm test -- --run

# Check code quality
lint:
	. venv/bin/activate && ruff check agents/ main.py
	cd frontend && npm run lint

# Format code
format:
	. venv/bin/activate && black agents/ main.py
	. venv/bin/activate && ruff check --fix agents/ main.py
	cd frontend && npm run format 2>/dev/null || npx prettier --write "src/**/*.{ts,tsx}"

# Start development servers
run:
	@echo "Starting backend on http://localhost:8000"
	@echo "Starting frontend on http://localhost:3000"
	@echo ""
	@echo "Press Ctrl+C to stop"
	@echo ""
	. venv/bin/activate && python main.py &
	cd frontend && npm run dev

# Clean generated files
clean:
	rm -rf venv/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .ruff_cache/
	rm -rf .mypy_cache/
	rm -rf frontend/node_modules/
	rm -rf frontend/dist/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
