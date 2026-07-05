# Checklist Migración Desktop – Vridik

## Hoy completado (75% límite)

- [x] S7-S10 integrados
- [x] prompt_v3 con estilo Ana Luisa
- [x] context_builder con boost personalización
- [x] eval_ana_luisa.py

## Mañana – antes de gastar tokens

1. [ ] Copiar archivos de Project Vridik → repo real
2. [ ] git commit -m "S7-S10 + estilo Ana Luisa"
3. [ ] python rag/ingest_desktop.py --source "~/Desktop/Giraldo Velasco Abogados" "~/Desktop/Marta Arias" --dry-run
4. [ ] Revisar data/desktop_manifest.csv (archivos nuevos vs skip)
5. [ ] Si tokens_ahorrados > 50%, ejecutar --commit
6. [ ] python -m pytest tests/ -k rag -v

## Pendiente (cuando renueve límite)

- [ ] scripts/build_ana_profile.py (muestreo 200 conversaciones)
- [ ] Correr eval con Ana Luisa (20 preguntas)
