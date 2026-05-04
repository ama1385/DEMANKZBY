#!/usr/bin/env bash
set -e

# DEMAN bot
nohup env TG_BOT_TOKEN="PUT_DEMAN_BOT_TOKEN" TG_OWNER_ID="PUT_OWNER_TELEGRAM_ID" TG_TENANT="DEMAN.STORE" \
  python3 /home/kabny/Downloads/arc/DEMANARC\ ARC\ \(1\)/DEMANARC\ ARC/backend/telegram_key_bot.py \
  >/tmp/tg-deman-bot.log 2>&1 &

# CLS bot
nohup env TG_BOT_TOKEN="PUT_CLS_BOT_TOKEN" TG_OWNER_ID="PUT_OWNER_TELEGRAM_ID" TG_TENANT="CLS-PREMIUM" \
  python3 /home/kabny/Downloads/arc/DEMANARC\ ARC\ \(1\)/DEMANARC\ ARC/backend/telegram_key_bot.py \
  >/tmp/tg-cls-bot.log 2>&1 &

echo "Bots started. Logs: /tmp/tg-deman-bot.log , /tmp/tg-cls-bot.log"
