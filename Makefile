.PHONY: setup up gpu host down logs test bench reset
setup:  ## crea .env si no existe
	@test -f .env || cp .env.example .env
up: setup
	docker compose up -d --build
gpu: setup
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
host: setup  ## Ollama instalado en Windows (GPU AMD)
	docker compose -f docker-compose.host-ollama.yml up -d --build
down:
	docker compose down
logs:
	docker compose logs -f api
test:  ## pruebas del backend (sin Docker, sin descargar modelos)
	python -m venv .venv && . .venv/bin/activate && pip install -q -r api/requirements.txt pytest && pytest tests -q
bench:  ## mide la velocidad real de tu equipo con los modelos configurados
	docker compose exec api python -m app.bench
reset:  ## borra volúmenes (modelos y voces descargados)
	docker compose down -v
