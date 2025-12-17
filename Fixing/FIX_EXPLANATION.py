"""
CORRECTION DU PROBLÈME D'ORDRE DANS LA CONCATÉNATION
====================================================

PROBLÈME IDENTIFIÉ:
------------------
Dans la fonction fix_DPR_data() (image 6, ligne ~684), tu utilises:

    groups = defaultdict(lambda: {'non_k9': {}, 'k9_values': defaultdict(set)})

Et plus loin (ligne ~635):
    
    groups[group_key]['k9_values'][k9_col].add(value)

❌ Le problème: set() ne préserve PAS l'ordre d'insertion en Python!
   Donc quand tu fais le join() plus tard, l'ordre est aléatoire.

SOLUTION:
---------
Remplacer set() par list() et éviter manuellement les doublons.

"""

# ============================================================================
# ANCIENNE VERSION (INCORRECTE) - ligne ~684 dans fix_DPR_data()
# ============================================================================

def fix_DPR_data_OLD(name, csv_file_path):
    # ... code précédent ...
    
    groups = defaultdict(lambda: {'non_k9': {}, 'k9_values': defaultdict(set)})  # ❌ set() ici!
    k9_prefixes = ['K9-APPLICATIONS']
    
    with open(csv_file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
        fieldnames = reader.fieldnames
        
        # ... code ...
        
        for row in reader:
            # ... code pour group_key ...
            
            # Accumulate unique K9 values for each K9 column
            for k9_col in k9_cols:
                value = row.get(k9_col, '').strip('""').strip()
                if value and value.upper() not in ['N/A', 'NAN', 'NONE', 'NULL', '']:
                    groups[group_key]['k9_values'][k9_col].add(value)  # ❌ add() sur un set!
        
        # ... plus tard, dans le join ...
        for k9_col in k9_cols:
            values = groups[group_data]['k9_values'].get(k9_col, set())
            if values:
                row_out[k9_col] = ' | '.join(sorted(values))  # ❌ sorted() ne suffit pas!


# ============================================================================
# NOUVELLE VERSION (CORRECTE)
# ============================================================================

def fix_DPR_data_NEW(name, csv_file_path):
    """
    Version corrigée qui préserve l'ordre d'apparition des valeurs
    """
    
    write_log(f"[{datetime.datetime.now()}] Starting consolidation for {csv_file_path}...")
    
    # ✅ Utiliser list() au lieu de set()
    groups = defaultdict(lambda: {'non_k9': {}, 'k9_values': defaultdict(list)})
    k9_prefixes = ['K9-APPLICATIONS']
    
    with open(csv_file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
        fieldnames = reader.fieldnames
        
        fieldnames = [field.strip('""').strip() for field in fieldnames]
        
        # Identify K9 and non-K9 columns
        k9_cols = [col for col in fieldnames if any(prefix in col for prefix in k9_prefixes)]
        non_k9_cols = [col for col in fieldnames if col not in k9_cols]
        openstack_skipped = 0
        
        row_count = 0
        
        for row in reader:
            row_count += 1
            
            # Skip row if the condition is met
            href_value = row.get('OPENSTACK__FLAVOR.OPENSTACK__LINKS.OPENSTACK__HREF', '')
            ).strip('""').strip()
            if href_value.startswith(
                'HTTPS://OPENSTACK-APAC02-CORE-PROD.XMP.NET.INTRA:8774/FLAVORS/'):
                openstack_skipped = openstack_skipped + 1
                continue
            
            # Create a group key based on ALL non-K9 fields, strip quotes and whitespace
            # from values
            group_key_parts = []
            for col in non_k9_cols:
                value = row.get(col, '').strip('""').strip()
                group_key_parts.append(value)
            
            group_key = '|||'.join(group_key_parts)
            
            # Store non-K9 values (only from first occurrence)
            if not groups[group_key]['non_k9']:
                groups[group_key]['non_k9'] = {col: row.get(col, '').strip('""').strip()
                                               for col in non_k9_cols}
            
            # ✅ Accumulate K9 values in ORDER, avoiding duplicates manually
            for k9_col in k9_cols:
                value = row.get(k9_col, '').strip('""').strip()
                if value and value.upper() not in ['N/A', 'NAN', 'NONE', 'NULL', '']:
                    # ✅ Vérifier si la valeur existe déjà avant de l'ajouter
                    if value not in groups[group_key]['k9_values'][k9_col]:
                        groups[group_key]['k9_values'][k9_col].append(value)
        
        write_log(f"[{datetime.datetime.now()}] Processed {row_count} rows into {len(groups)} "
                  f"unique groups, deduction: {row_count - len(groups)} duplicate K9 entries removed, "
                  f"Openstack removed: {openstack_skipped}")
    
    output_path = csv_file_path.replace('.csv', '_fixed.csv')
    write_log(f"[{datetime.datetime.now()}] Writing consolidated data to {output_path}...")
    
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', quotechar='"',
                                quoting=csv.QUOTE_ALL)
        writer.writeheader()
        
        written_count = 0
        
        for group_key, group_data in groups.items():
            row_out = group_data['non_k9'].copy()
            
            # ✅ Maintenant le join() préserve l'ordre d'apparition!
            for k9_col in k9_cols:
                values = group_data['k9_values'].get(k9_col, [])
                if values:
                    # ✅ Pas besoin de sorted(), on garde l'ordre naturel
                    row_out[k9_col] = ' | '.join(values)
                else:
                    row_out[k9_col] = ''
            
            writer.writerow(row_out)
            written_count += 1
    
    consolidated_count = len(groups)
    
    write_log(f"[{datetime.datetime.now()}] File written successfully")
    
    # Free the RAM
    groups.clear()
    gc.collect()


# ============================================================================
# RÉSUMÉ DES CHANGEMENTS
# ============================================================================

"""
CHANGEMENTS À EFFECTUER:

1. Ligne ~684 (dans la fonction fix_DPR_data):
   AVANT: groups = defaultdict(lambda: {'non_k9': {}, 'k9_values': defaultdict(set)})
   APRÈS:  groups = defaultdict(lambda: {'non_k9': {}, 'k9_values': defaultdict(list)})
   
2. Ligne ~635 (accumulation des valeurs K9):
   AVANT:
       groups[group_key]['k9_values'][k9_col].add(value)
   
   APRÈS:
       if value not in groups[group_key]['k9_values'][k9_col]:
           groups[group_key]['k9_values'][k9_col].append(value)

3. Ligne ~664 (lors du join):
   AVANT:
       row_out[k9_col] = ' | '.join(sorted(values))
   
   APRÈS:
       row_out[k9_col] = ' | '.join(values)
   (Plus besoin de sorted(), l'ordre est déjà correct!)

POURQUOI ÇA MARCHE:
-------------------
- list() préserve l'ordre d'insertion (depuis Python 3.7+)
- En vérifiant "if value not in list" avant append(), on évite les doublons
- L'ordre des éléments dans la liste correspond à l'ordre d'apparition dans le CSV
- Donc AppA|AppB|AppC et Critique|Severe|Low seront toujours cohérents!

IMPACT SUR LES PERFORMANCES:
----------------------------
- La vérification "if value not in list" est O(n) au lieu de O(1) pour set
- Mais comme tu as généralement peu de valeurs K9 par groupe (3-10), 
  l'impact est négligeable
- Si tu as BEAUCOUP de valeurs (>100), tu peux optimiser avec:
  
    seen = set()
    ordered_list = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered_list.append(value)
"""
