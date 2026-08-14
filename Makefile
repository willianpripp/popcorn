# Deploy to the lab VM, same convention as the calendar's repo: rsync the
# working tree (never .git, never docs) and rebuild. The .env lives only on
# the host and rsync without --delete never touches it.

DIR = /srv/lab/popcorn

.PHONY: deploy up down logs status

deploy:
	rsync -a --exclude .git --exclude .gitignore --exclude Makefile \
	      --exclude README.md --exclude STATUS.md ./ lab:$(DIR)/
	ssh lab 'cd $(DIR) && docker compose up -d --build'

up:
	ssh lab 'cd $(DIR) && docker compose up -d'

down:
	ssh lab 'cd $(DIR) && docker compose down'

logs:
	ssh lab 'cd $(DIR) && docker compose logs --tail=100 -f'

status:
	ssh lab 'cd $(DIR) && docker compose ps'
