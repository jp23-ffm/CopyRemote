1. inventory/templates/inventory/table-lazyload.html

  Primary row (ligne ~373) — ajout d'un {% elif server_group.serverunique %} après le check variable_fields. Si le champ
   n'est ni dans constant_fields ni dans variable_fields, on regarde l'objet serverunique via le filtre lookup (qui fait
   getattr sur l'instance Django).

  Detail rows (ligne ~420) — même logique : quand instance|lookup:field.name retourne vide (car Server n'a pas les
  champs BC), on tombe sur le fallback server_group.serverunique. Les données BC étant par hostname (pas par instance),
  c'est la même valeur pour chaque ligne de détail.

  serversData / instancesData JS — les objets JavaScript pour la modale de détail incluent maintenant les valeurs
  ServerUnique en fallback, pour que le right-click "Server Details" affiche aussi les champs BC.

  2. inventory/static/inventory/js/column-lazy-loader.js

  initializeState() — parse le json-data pour construire state.externalModelFields, un Set des noms de champs ayant
  model_extra dans field_labels.json.

  handleColumnCheckboxChange() — si la checkbox cochée correspond à un champ external ET qu'il n'est pas déjà chargé →
  updateVisibleColumnsInUrl() puis reload de la page (le backend fetchera alors ServerUnique).

  handleCategoryCheckboxChange() — idem au niveau catégorie : si au moins un champ de la catégorie est external →
  reload. Sinon, AJAX lazy load classique.

  Flux complet

  1. User coche "Priority Asset" (ou la catégorie "Business Continuity")
  2. Le lazy loader détecte model_extra → met à jour visible_columns dans l'URL → reload
  3. Le backend (views.py:558-571) voit les colonnes BC dans visible_columns → query ServerUnique
  4. Le template rend les données via server_group.serverunique|lookup:field.name
  5. Si l'user décoche → simple display: none, pas de reload