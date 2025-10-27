<#
.SYNOPSIS
    Traite et sauvegarde les pièces jointes d'un email (version migrée vers Graph)
    
.DESCRIPTION
    Cette fonction remplace l'ancienne version EWS par une version compatible
    avec les objets messages Graph retournés par nos wrappers.
    
.PARAMETER O_CheckMail
    Objet message compatible (retourné par Get-EwsCompatMessages)
    
.PARAMETER S_PathArchiveAttachments
    Chemin où sauvegarder les pièces jointes
    
.RETURNS
    Array @(StatusCode, Message)
    - StatusCode 0 = PDF trouvés et sauvegardés
    - StatusCode 1 = Aucun PDF trouvé
    - Message = Description du résultat
#>
Function F_GetAttachmentsObject {
    Param(
        [Parameter(Mandatory = $true)] [Object]$O_CheckMail,
        [Parameter(Mandatory = $true)] [string]$S_PathArchiveAttachments
    )
    
    $return = @()
    $S_Error = 1
    $S_Processing = 1
    $I_countAttchment = 0
    
    # Vérifier qu'il y a des pièces jointes
    If ($O_CheckMail.Attachments.count -gt 0) {
        Write-Host -ForegroundColor Green "more file"
        
        # Parcourir les pièces jointes
        ForEach ($O_ValAttachmentsCount In $O_CheckMail.Attachments) {
            Write-Host -ForegroundColor Green "file $I_countAttchment"
            
            # Vérifier si c'est un fichier PDF (en regardant les 4 derniers caractères du nom)
            If ($($O_ValAttachmentsCount.Name.ToString()).substring($($O_ValAttachmentsCount.Name.ToString()).length - 4) -like '*.pdf') {
                Write-Host -ForegroundColor Green "file pdf find"
                $I_countAttchment++
            }
        }
    }
    
    # Si au moins un PDF a été trouvé
    If ($I_countAttchment -gt 0) {
        If ($I_countAttchment -eq 1) {
            # Un seul PDF trouvé
            ForEach ($O_ValAttachments In $O_CheckMail.Attachments) {
                
                # Vérifier que c'est un PDF
                If ($($O_ValAttachments.Name.ToString()).substring($($O_ValAttachments.Name.ToString()).length - 4) -like '*.pdf') {
                    Try {
                        # === CHANGEMENT : Utilisation des propriétés Graph ===
                        # Charger le contenu de la pièce jointe si pas déjà fait
                        If (-not $O_ValAttachments.ContentBytes) {
                            $O_ValAttachments.Load()
                        }
                        
                        # Créer le chemin complet du fichier
                        $filePath = $S_PathArchiveAttachments + $O_ValAttachments.Name.ToString()
                        
                        # === CHANGEMENT : Conversion Base64 vers bytes puis sauvegarde ===
                        # Graph retourne le contenu en Base64, il faut le convertir
                        $fileBytes = [System.Convert]::FromBase64String($O_ValAttachments.ContentBytes)
                        
                        # Sauvegarder le fichier sur le disque
                        [System.IO.File]::WriteAllBytes($filePath, $fileBytes)
                        
                        Write-Host -ForegroundColor Green $O_ValAttachments.Name.ToString()
                        
                        $S_Error = 0
                        $S_Processing = 0
                    }
                    Catch {
                        $S_Error = 0
                        Write-Host -ForegroundColor Red $($_.Exception.Message)
                    }
                    
                    If ($S_Error -eq 1) {
                        # Erreur lors de la sauvegarde - code inaccessible car $S_Error est mis à 0 dans le Try
                        # Gardé pour compatibilité avec la logique originale
                    }
                }
            }
        }
        Else {
            # Plusieurs PDFs trouvés
            ForEach ($O_ValAttachments In $O_CheckMail.Attachments) {
                
                # Vérifier que c'est un PDF ET que ce n'est pas le fichier Terms Of Sale
                If ($($O_ValAttachments.Name.ToString()).substring($($O_ValAttachments.Name.ToString()).length - 4) -like '*.pdf' -and
                    $O_ValAttachments.Name.ToString() -ne "FR_COMMERCIAL_Terms Of Sale.pdf") {
                    
                    Try {
                        # === CHANGEMENT : Utilisation des propriétés Graph ===
                        # Charger le contenu de la pièce jointe si pas déjà fait
                        If (-not $O_ValAttachments.ContentBytes) {
                            $O_ValAttachments.Load()
                        }
                        
                        # Créer le chemin complet du fichier
                        $filePath = $S_PathArchiveAttachments + $O_ValAttachments.Name.ToString()
                        
                        # === CHANGEMENT : Conversion Base64 vers bytes puis sauvegarde ===
                        $fileBytes = [System.Convert]::FromBase64String($O_ValAttachments.ContentBytes)
                        
                        # Sauvegarder le fichier sur le disque
                        [System.IO.File]::WriteAllBytes($filePath, $fileBytes)
                        
                        Write-Host -ForegroundColor Green $O_ValAttachments.Name.ToString()
                        
                        $S_Error = 0
                        $S_Processing = 0
                    }
                    Catch {
                        $S_Error = 0
                        Write-Host -ForegroundColor Red $($_.Exception.Message)
                    }
                    
                    If ($S_Error -eq 1) {
                        # Erreur lors de la sauvegarde
                    }
                }
            }
        }
    }
    
    # Préparer le résultat
    If ($S_Processing -eq 0) {
        $return += 0
        $return += "- PURCHASE_WORKFLOW_ORDER $($O_CheckMail.Subject) document is backuped<br><br>"
        $return += "- PURCHASE_WORKFLOW_ORDER $($O_CheckMail.Subject) document is backuped"
    }
    Else {
        $return += 1
        $return += "- PURCHASE_WORKFLOW_ORDER $($O_CheckMail.Subject) none document<br><br>"
        $return += "- PURCHASE_WORKFLOW_ORDER $($O_CheckMail.Subject) none document"
    }
    
    Return $return
}


<#
===========================================
EXEMPLE D'UTILISATION
===========================================
#>

# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

# Connexion Graph
Connect-MgGraph -Scopes "Mail.ReadWrite", "Mail.ReadWrite.Shared"

# Initialiser la connexion pour un utilisateur
Initialize-EwsCompatConnection -UserEmail "user@domain.com"

# Récupérer un message avec pièces jointes
$messages = Get-EwsCompatMessages -FolderId $folderId -Top 1
$message = $messages.Items[0]

# Traiter les pièces jointes
$result = F_GetAttachmentsObject -O_CheckMail $message `
                                 -S_PathArchiveAttachments "C:\Temp\Attachments\"

If ($result[0] -eq 0) {
    Write-Host " Pièces jointes sauvegardées avec succès"
    Write-Host $result[1]
}
Else {
    Write-Host "⚠ Aucune pièce jointe PDF trouvée"
    Write-Host $result[1]
}


<#
===========================================
NOTES DE MIGRATION
===========================================

CHANGEMENTS PRINCIPAUX :
1. Remplacement de $O_ValAttachments.Content par $O_ValAttachments.ContentBytes
2. Ajout de .Load() pour charger le contenu si nécessaire
3. Conversion Base64 → bytes avec [System.Convert]::FromBase64String()
4. Utilisation de [System.IO.File]::WriteAllBytes() au lieu de FileStream

COMPATIBILITÉ :
-  Fonctionne avec les objets retournés par Get-EwsCompatMessages
-  Garde la même signature de fonction
-  Retourne le même format @(code, message)
-  Même logique métier (filtre PDF, exclut Terms Of Sale)

PROPRIÉTÉS UTILISÉES :
- $O_CheckMail.Attachments       → Collection de pièces jointes
- $attachment.Name                → Nom du fichier
- $attachment.ContentBytes        → Contenu en Base64 (après .Load())
- $attachment.Load()              → Charge le contenu depuis Graph

GESTION D'ERREURS :
- Try-Catch autour de la sauvegarde de fichier
- Messages d'erreur affichés en rouge
- Statut retourné : 0 = succès, 1 = échec
#>