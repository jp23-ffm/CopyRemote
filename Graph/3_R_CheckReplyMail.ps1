# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

<#
.SYNOPSIS
    Vérifie et répond aux emails de commande (version migrée vers Graph)
    
.DESCRIPTION
    Cette fonction remplace l'ancienne version EWS par une version Graph.
    Elle recherche les commandes en attente de réponse et envoie les réponses appropriées.
#>
Function R_CheckReplyMail {
    param(
        [Parameter(Mandatory = $true)] [string]$S_Mail,
        [Parameter(Mandatory = $false)] [string]$S_LoginExchange,
        [Parameter(Mandatory = $false)] [string]$S_PasswordExchange,
        [Parameter(Mandatory = $false)] [string]$S_Domain,
        [Parameter(Mandatory = $true)] [string]$S_FolderRoot,
        [Parameter(Mandatory = $true)] [string]$S_FolderProvider,
        [Parameter(Mandatory = $true)] [string]$S_FolderSource,
        [Parameter(Mandatory = $true)] [string]$S_FolderDestination,
        [Parameter(Mandatory = $true)] [string]$S_FolderError,
        [Parameter(Mandatory = $true)] [string]$S_Connectionstring,
        [Parameter(Mandatory = $true)] [string]$S_Css
    )
    
    # Connexion ADODB (inchangée)
    $I_adOpenStatic = 3
    $I_adLockOptimistic = 3
    $O_Connection = New-Object -ComObject ADODB.Connection
    $O_Connection.Open($S_Connectionstring)
    $O_RecordsetInsertUpdate = New-Object -ComObject ADODB.Recordset
    $O_RecordsetRead = New-Object -ComObject ADODB.Recordset
    $O_RecordsetReadSecond = New-Object -ComObject ADODB.Recordset
    
    # === CHANGEMENT : Initialisation Graph au lieu de EWS ===
    Try {
        $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_Mail
        
        if (-not $connectionResult.Success) {
            Write-Host -ForegroundColor Red "Erreur lors de l'initialisation de la connexion Graph"
            $O_Connection.Close()
            Return
        }
        
        Write-Host -ForegroundColor Green "Connexion Graph initialisée pour: $S_Mail"
    }
    Catch {
        Write-Host -ForegroundColor Red "Erreur critique lors de la connexion Graph: $_"
        R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail] - Graph connection failed" `
                        -MsgError "Impossible de se connecter à Graph: $($_.Exception.Message)"
        $O_Connection.Close()
        Return
    }
    
    # === Navigation dans les dossiers (avec gestion d'erreur) ===
    Try {
        # Étape 1: Trouver le dossier racine
        $O_FolderRootMailAutomate = Get-EwsCompatFolder -ParentFolderId "Inbox" -DisplayName $S_FolderRoot
        
        if ($null -eq $O_FolderRootMailAutomate -or $O_FolderRootMailAutomate.Count -eq 0) {
            Write-Host -ForegroundColor Green "Folder Root not found: $S_FolderRoot"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail], Folder $S_FolderRoot not available"
            $O_Connection.Close()
            Return
        }
        
        $O_FolderRootMailAutomate = $O_FolderRootMailAutomate[0]
        
        # Étape 2: Trouver le dossier Provider
        $O_FolderProviderMailAutomate = Get-EwsCompatFolder -ParentFolderId $O_FolderRootMailAutomate.Id -DisplayName $S_FolderProvider
        
        if ($null -eq $O_FolderProviderMailAutomate -or $O_FolderProviderMailAutomate.Count -eq 0) {
            Write-Host -ForegroundColor Green "Folder Provider not found: $S_FolderProvider"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail], Folder $S_FolderProvider not available"
            $O_Connection.Close()
            Return
        }
        
        $O_FolderProviderMailAutomate = $O_FolderProviderMailAutomate[0]
        
        # Étape 3: Trouver les sous-dossiers
        $allSubFolders = Get-EwsCompatFolder -ParentFolderId $O_FolderProviderMailAutomate.Id
        
        $O_FolderTODOMailAutomate = $allSubFolders | Where-Object { $_.DisplayName -eq $S_FolderSource }
        $O_FolderDONEMailAutomate = $allSubFolders | Where-Object { $_.DisplayName -eq $S_FolderDestination }
        $O_FolderERRORMailAutomate = $allSubFolders | Where-Object { $_.DisplayName -eq $S_FolderError }
        
        # Vérifications
        if ($null -eq $O_FolderTODOMailAutomate) {
            Write-Host -ForegroundColor Green "Folder TODO not found: $S_FolderSource"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail], Folder TODO not available"
            $O_Connection.Close()
            Return
        }
        
        if ($null -eq $O_FolderDONEMailAutomate) {
            Write-Host -ForegroundColor Green "Folder DONE not found: $S_FolderDestination"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail], Folder DONE not available"
            $O_Connection.Close()
            Return
        }
        
        if ($null -eq $O_FolderERRORMailAutomate) {
            Write-Host -ForegroundColor Green "Folder ERROR not found: $S_FolderError"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail], Folder ERROR not available"
            $O_Connection.Close()
            Return
        }
        
        Write-Host -ForegroundColor Green "Tous les dossiers ont été trouvés"
    }
    Catch {
        Write-Host -ForegroundColor Red "❌ Timeout/Erreur lors de la navigation dans les dossiers: $_"
        R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail] - Folder navigation failed" `
                        -MsgError "Impossible de naviguer dans les dossiers: $($_.Exception.Message)"
        $O_Connection.Close()
        Return
    }
    
    # === Traitement des commandes en attente de réponse ===
    Write-Host -ForegroundColor Green "Requête dans une requête à faire"
    $O_RecordsetRead.Open(
        "select T_PurchaseCart_ID From T_PurchaseCart where T_PurchaseCart_StateInt = 13", 
        $O_Connection, 
        $I_adOpenStatic, 
        $I_adLockOptimistic
    )
    
    If (-Not $O_RecordsetRead.EOF) {
        $O_RecordsetRead.MoveFirst()
        $I_CountMailchecked = 0
        $I_TotalCommands = 0
        
        # Compter le nombre total de commandes
        Do {
            $I_TotalCommands++
            $O_RecordsetRead.MoveNext()
        } Until ($O_RecordsetRead.EOF)
        
        Write-Host -ForegroundColor Cyan "🚀 $I_TotalCommands commandes à traiter"
        $O_RecordsetRead.MoveFirst()
        
        Do {
            Try {
                Write-Host -ForegroundColor Green "envoie mail"
                
                # Récupérer les informations de la commande
                $O_RecordsetReadSecond.Open(
                    "select top 1 T_PurchaseMailReceived_ReplyMail, T_PurchaseMailReceived_T_PurchaseCart_ID " +
                    "From T_PurchaseMailReceived " +
                    "Where T_PurchaseMailReceived_T_PurchaseCart_ID = " + 
                    $($O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value) + 
                    " order by T_PurchaseMailReceived_ID desc", 
                    $O_Connection, 
                    $I_adOpenStatic, 
                    $I_adLockOptimistic
                )
                
                $O_RecordsetReadSecond.MoveFirst()
                
                # Préparer la recherche de l'email dans le dossier DONE
                $I_T_PurchaseMailReceived_T_PurchaseCart_ID = $($O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceived_T_PurchaseCart_ID").Value)
                
                # === CHANGEMENT : Recherche via Graph au lieu de EWS ===
                # Créer un filtre de recherche pour trouver l'email correspondant
                $searchSubject = "[PURCHASE_WORKFLOW_ORDER][ID_$I_T_PurchaseMailReceived_T_PurchaseCart_ID]"
                
                Write-Verbose "Recherche de l'email avec sujet contenant: $searchSubject"
                
                # Récupérer les messages du dossier DONE et filtrer
                $allMessages = Get-MgUserMailFolderMessage -UserId $script:EwsCompat_CurrentUser `
                                                           -MailFolderId $O_FolderDONEMailAutomate.Id `
                                                           -Filter "contains(subject, '$searchSubject')" `
                                                           -Top 1
                
                if ($allMessages) {
                    # Convertir en objet compatible
                    $O_ReplyOnMail = New-EwsCompatMessage -GraphMessage $allMessages[0] -GraphAttachments $null
                    
                    Write-Host -ForegroundColor Green "Email trouvé pour répondre"
                    
                    # === CHANGEMENT : Réponse via Graph au lieu de EWS ===
                    $replyBody = $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceived_ReplyMail").Value
                    
                    $replyResult = Send-EwsCompatReply -MessageId $O_ReplyOnMail.Id `
                                                       -ReplyBody $replyBody `
                                                       -ReplyToAll $true
                    
                    if ($replyResult.Success) {
                        Write-Host -ForegroundColor Green "Réponse envoyée avec succès"
                        
                        # Mettre à jour le statut dans la base de données
                        $O_RecordsetInsertUpdate.Open(
                            "Update T_PurchaseCart set T_PurchaseCart_StateInt = '14', T_PurchaseCart_StateString = 'REPLY SENT' " +
                            "where T_PurchaseCart_ID = '" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "'", 
                            $O_Connection, 
                            $I_adOpenStatic, 
                            $I_adLockOptimistic
                        )
                    }
                    else {
                        Write-Host -ForegroundColor Red "Erreur lors de l'envoi de la réponse: $($replyResult.Error)"
                        # On continue quand même avec les autres commandes
                    }
                }
                else {
                    Write-Host -ForegroundColor Yellow "⚠️ Email non trouvé dans le dossier DONE pour la commande $I_T_PurchaseMailReceived_T_PurchaseCart_ID"
                }
                
                $O_RecordsetReadSecond.Close()
                $I_CountMailchecked++
                
            }
            Catch {
                # === GESTION D'ERREUR : FAIL-FAST ===
                Write-Host -ForegroundColor Red "❌ Erreur Graph détectée: $_"
                Write-Host -ForegroundColor Red "Arrêt du traitement. $I_CountMailchecked commandes traitées sur $I_TotalCommands."
                
                # Alerte
                R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReplyMail] - Graph timeout/error" `
                                -MsgError "Erreur détectée après $I_CountMailchecked commandes traitées. Commandes restantes: $($I_TotalCommands - $I_CountMailchecked). Erreur: $($_.Exception.Message)"
                
                # Fermer le recordset s'il est ouvert
                Try { $O_RecordsetReadSecond.Close() } Catch {}
                
                # SORTIE IMMÉDIATE
                Break
            }
            
            $O_RecordsetRead.MoveNext()
            
        } Until ($O_RecordsetRead.EOF)
        
        Write-Host -ForegroundColor Cyan "✅ Traitement terminé : $I_CountMailchecked/$I_TotalCommands commandes traitées"
    }
    Else {
        Write-Host -ForegroundColor Green "Aucune commande en attente de réponse (StateInt = 13)"
    }
    
    # Fermeture propre
    $O_RecordsetRead.Close()
    $O_Connection.Close()
}


<#
===========================================
EXEMPLE D'UTILISATION
===========================================
#>

# IMPORTANT: Vous devez d'abord vous connecter à Microsoft Graph
Connect-MgGraph -Scopes "Mail.ReadWrite", "Mail.ReadWrite.Shared", "Mail.Send", "Mail.Send.Shared"

# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

# Définir vos variables
$S_Connectionstring = "Provider=SQLOLEDB;Data Source=...;Initial Catalog=...;User ID=...;Password=..."
$S_Css = "/* Votre CSS */"

# Appel de la fonction
R_CheckReplyMail -S_Mail "emea.purchase.digital.workflow@bnpparibas.com" `
                 -S_LoginExchange "SVC.EMEAWINTEL.EWS" `
                 -S_PasswordExchange "dummy" `
                 -S_Domain "MERCURY\" `
                 -S_FolderRoot "_01 AUTOMATE MAIL" `
                 -S_FolderProvider "DELL" `
                 -S_FolderSource "TODO" `
                 -S_FolderDestination "DONE" `
                 -S_FolderError "ERROR" `
                 -S_Connectionstring $S_Connectionstring `
                 -S_Css $S_Css