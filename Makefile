help:
	@echo "Available commands:"
	@echo "  frontend  - Start the frontend development server"
	@echo "  backend   - Start the backend development server"

frontend:
	cd frontend && npm run dev

backend:
	cd backend &&uvicorn server:app --reload
.PHONY: help frontend backend

help:
	@echo "Available commands:"
	@echo "  frontend  - Start the frontend development server"
	@echo "  backend   - Start the backend development server"

frontend:
	cd frontend && npm run dev

backend:
	cd backend && uvicorn server:app --reload --host 127.0.0.1 --port 8000