#!/usr/bin/env bash
# Запуск всего market_intel (кроме Cloudflare — тот управляется через Dashboard)
set -e

echo "=== SBF market_intel — запуск ==="

systemctl --user daemon-reload

systemctl --user enable --now sbf-web.service
systemctl --user enable --now sbf-publish.timer
systemctl --user enable --now sbf-collectors.timer
systemctl --user enable --now sbf-morning.timer
systemctl --user enable --now sbf-quotes.service

echo ""
echo "=== Статус ==="
systemctl --user status sbf-web.service sbf-publish.timer sbf-collectors.timer sbf-morning.timer sbf-quotes.service \
  --no-pager -l | grep -E "Active:|Loaded:|Trigger:|●|○"

echo ""
echo "Сайт:     https://lp.sbfconsult.com"
echo "Локально: http://localhost:8085"
