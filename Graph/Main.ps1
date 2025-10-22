# Import du module de wrappers
# Assurez-vous que le fichier EwsGraphWrappers.psm1 est dans votre chemin de modules
Import-Module .\EwsGraphWrappers.psm1 -Force

Function R_CheckReceivedMail {
    param(
        [Parameter(Mandatory = $true)] [string]$S_Mail,
        # Les paramètres LoginExchange, PasswordExchange et Domain ne sont plus nécessaires avec Graph
        # On les garde pour compatibilité mais ils ne seront pas utilisés
        [Parameter(Mandatory = $false)] [string]$S_LoginExchange,
        [Parameter(Mandatory = $false)] [string]$S_PasswordExchange,
        [Parameter(Mandatory = $false)] [string]$S_Domain,
        [Parameter(Mandatory = $true)] [string]$S_FolderRoot,
        [Parameter(Mandatory = $true)] [string]$S_FolderProvider,
        [Parameter(Mandatory = $true)] [string]$S_FolderSource,
        [Parameter(Mandatory = $true)] [string]$S_FolderDestination,
        [Parameter(Mandatory = $true)] [string]$S_FolderError,
        [Parameter(Mandatory = $true)] [string]$S_PathArchiveAttachments,
        [Parameter(Mandatory = $true)] [string]$S_Connectionstring
    )
    
    # Connexion ADODB (inchangée)
    $I_adOpenStatic = 3
    $I_adLockOptimistic = 3
    $O_Connection = New-Object -ComObject ADODB.Connection
    $O_Connection.Open($S_Connectionstring)
    $O_RecordsetInsertUpdate = New-Object -ComObject ADODB.Recordset
    
    # === CHANGEMENT PRINCIPAL : Remplacement EWS par Graph ===
    # Au lieu de créer un ExchangeService, on initialise la connexion Graph
    $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_Mail
    
    if (-not $connectionResult.Success) {
        Write-Host -ForegroundColor Red "Erreur lors de l'initialisation de la connexion Graph"
        $O_Connection.Close()
        return
    }
    
    Write-Host -ForegroundColor Green "Connexion Graph initialisée pour: $S_Mail"
    
    # === Navigation dans les dossiers (syntaxe adaptée mais logique identique) ===
    
    try {
        # Étape 1: Trouver le dossier racine dans Inbox
        $O_FolderRootMailAutomate = Get-EwsCompatFolder -ParentFolderId "Inbox" -DisplayName $S_FolderRoot
        
        if ($null -eq $O_FolderRootMailAutomate -or $O_FolderRootMailAutomate.Count -eq 0) {
            Write-Host -ForegroundColor Green "Folder Root not found: $S_FolderRoot"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Folder $S_FolderRoot not available"
            return
        }
        
        # Prendre le premier résultat
        $O_FolderRootMailAutomate = $O_FolderRootMailAutomate[0]
        Write-Host -ForegroundColor Green "Dossier racine trouvé: $($O_FolderRootMailAutomate.DisplayName)"
        
        # Étape 2: Trouver le dossier Provider
        $O_FolderProviderMailAutomate = Get-EwsCompatFolder -ParentFolderId $O_FolderRootMailAutomate.Id -DisplayName $S_FolderProvider
        
        if ($null -eq $O_FolderProviderMailAutomate -or $O_FolderProviderMailAutomate.Count -eq 0) {
            Write-Host -ForegroundColor Green "Folder Provider not found: $S_FolderProvider"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Folder $S_FolderProvider not available"
            return
        }
        
        $O_FolderProviderMailAutomate = $O_FolderProviderMailAutomate[0]
        Write-Host -ForegroundColor Green "Dossier Provider trouvé: $($O_FolderProviderMailAutomate.DisplayName)"
        
        # Étape 3: Trouver les dossiers TODO, DONE et ERROR
        $allSubFolders = Get-EwsCompatFolder -ParentFolderId $O_FolderProviderMailAutomate.Id
        
        $O_FolderTODOMailAutomate = $allSubFolders | Where-Object { $_.DisplayName -eq $S_FolderSource }
        $O_FolderDONEMailAutomate = $allSubFolders | Where-Object { $_.DisplayName -eq $S_FolderDestination }
        $O_FolderERRORMailAutomate = $allSubFolders | Where-Object { $_.DisplayName -eq $S_FolderError }
        
        $I_CountMailchecked = 0
        
        # Vérifications des dossiers
        if ($null -eq $O_FolderTODOMailAutomate) {
            Write-Host -ForegroundColor Green "Folder TODO not found: $S_FolderSource"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Folder TODO not available"
            return
        }
        
        if ($null -eq $O_FolderDONEMailAutomate) {
            Write-Host -ForegroundColor Green "Folder DONE not found: $S_FolderDestination"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Folder DONE not available"
            return
        }
        
        if ($null -eq $O_FolderERRORMailAutomate) {
            Write-Host -ForegroundColor Green "Folder ERROR not found: $S_FolderError"
            R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Folder ERROR not available"
            return
        }
        
        Write-Host -ForegroundColor Green "Tous les dossiers ont été trouvés"
        
        # === Traitement des messages ===
        if ($O_FolderTODOMailAutomate.TotalCount -ne 0) {
            $I_CountMail = $O_FolderTODOMailAutomate.TotalCount
            Write-Host -ForegroundColor Green "Number of mails to check: $I_CountMail"
            
            Do {
                # Récupérer le message le plus ancien (tri ascendant)
                $O_CheckMailCollection = Get-EwsCompatMessages -FolderId $O_FolderTODOMailAutomate.Id -Top 1 -OrderBy "DateTimeReceived" -Ascending $true
                
                # Charger les données (méthode factice pour compatibilité)
                $O_CheckMailCollection.Load()
                
                # Prendre le premier message
                $O_CheckMail = $O_CheckMailCollection.Items[0]
                
                # Les attachments sont déjà chargés automatiquement avec Graph
                Try {
                    # Méthode factice pour compatibilité
                    $O_CheckMail.Attachments | ForEach-Object { $_.Load() }
                }
                Catch {
                    Write-Host -ForegroundColor Green "Error on load attachment"
                }
                
                # === Traitement selon le type de mail (logique inchangée) ===
                
                # Type 1: Mail PURCHASE WORKFLOW ORDER
                if ($O_CheckMail.Subject -like '*[PURCHASE WORKFLOW ORDER]*' -and $O_CheckMail.Subject -like '*ID_*') {
                    Write-Host -ForegroundColor Green "Format de mail conforme a traiter"
                    Write-Host -ForegroundColor Green $O_CheckMail.Subject
                    Write-Host -ForegroundColor Green $O_CheckMail.From.Address
                    
                    # Appel de votre fonction de traitement des attachments
                    $A_F_GetAttachmentsObject = F_GetAttachmentsObject -O_CheckMail $O_CheckMail -S_PathArchiveAttachments $S_PathArchiveAttachments
                    
                    if ($A_F_GetAttachmentsObject[0] -eq 0) {
                        Write-Host -ForegroundColor Green "OK Traitement avec document pdf"
                        R_AddMailInDB -S_PathArchiveAttachments $S_PathArchiveAttachments `
                                      -B_FilePdf $true `
                                      -O_CheckMail $O_CheckMail `
                                      -S_Connectionstring $S_Connectionstring
                    }
                    elseif ($A_F_GetAttachmentsObject[0] -eq 1) {
                        Write-Host -ForegroundColor Green "OK Traitement sans document"
                        R_AddMailInDB -S_PathArchiveAttachments $S_PathArchiveAttachments `
                                      -B_FilePdf $false `
                                      -O_CheckMail $O_CheckMail `
                                      -S_Connectionstring $S_Connectionstring
                    }
                    else {
                        Write-Host -ForegroundColor Green "Error"
                    }
                    
                    Write-Host -ForegroundColor Green $A_F_GetAttachmentsObject[1]
                    $O_CheckMail.Items.Move($O_FolderDONEMailAutomate.Id)
                }
                
                # Type 2: Mail confirmation de commande Dell
                elseif (($O_CheckMail.Subject -like 'Your Dell Order Has Been Confirmed: Order #*' -and $O_CheckMail.Subject -like '*Purchase Order #*') -or 
                        ($O_CheckMail.Subject -like 'Votre commande Dell est confirmée. Commande*' -and $O_CheckMail.Subject -like '*Votre bon de commande numéro*')) {
                    
                    Write-Host -ForegroundColor Green "Mail receive for confirmation order"
                    Write-Host -ForegroundColor Green $O_CheckMail.Subject
                    Write-Host -ForegroundColor Green $O_CheckMail.From.Address
                    
                    $A_F_GetAttachmentsObject = F_GetAttachmentsObject -O_CheckMail $O_CheckMail -S_PathArchiveAttachments $S_PathArchiveAttachments
                    
                    if ($A_F_GetAttachmentsObject[0] -eq 0) {
                        Write-Host -ForegroundColor Green "Fichier pdf trouvé"
                        
                        foreach ($O_ValAttachments in $O_CheckMail.Attachments) {
                            if ($O_ValAttachments.Name.ToString() -ne "FR_COMMERCIALTerms Of Sale.pdf") {
                                $A_F_ReadFilePdf = F_ReadFilePdf -S_PathArchiveAttachments $S_PathArchiveAttachments `
                                                                  -S_fileName $O_ValAttachments.Name.ToString()
                                
                                R_AddMailConfirmOrderInDB -S_PathArchiveAttachments $S_PathArchiveAttachments `
                                                          -O_CheckMail $O_CheckMail `
                                                          -S_Connectionstring $S_Connectionstring `
                                                          -A_F_ReadFilePdf $A_F_ReadFilePdf
                            }
                        }
                        
                        $O_CheckMail.Items.Move($O_FolderDONEMailAutomate.Id)
                    }
                    else {
                        Write-Host -ForegroundColor Green "Format de mail non conforme devrait avoir une piece jointe"
                        Write-Host -ForegroundColor Green $O_CheckMail.Subject
                        Write-Host -ForegroundColor Green $O_CheckMail.From.Address
                        
                        R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Mail not compliance for the process" `
                                        -MsgError "$($O_CheckMail.Subject) An attachment should be present please check it!, mail has been moved in the folder ERROR mailbox purchase"
                        
                        $O_CheckMail.Items.Move($O_FolderERRORMailAutomate.Id)
                    }
                }
                
                # Type 3: Mail de gouvernance BNP
                elseif ($O_CheckMail.Subject.ToUpper() -like '*COMMANDE*' -and 
                        $O_CheckMail.Subject.ToUpper() -like '*BNP*' -and 
                        $O_CheckMail.Subject.ToUpper() -like '*DELL*') {
                    
                    Write-Host -ForegroundColor Green "Mail receive for confirmation order governance"
                    Write-Host -ForegroundColor Green "Format de mail conforme a traiter"
                    Write-Host -ForegroundColor Green $O_CheckMail.Subject
                    Write-Host -ForegroundColor Green $O_CheckMail.From.Address
                    
                    $A_F_GetAttachmentsObject = F_GetAttachmentsObject -O_CheckMail $O_CheckMail -S_PathArchiveAttachments $S_PathArchiveAttachments
                    
                    if ($A_F_GetAttachmentsObject[0] -eq 0) {
                        Write-Host -ForegroundColor Green "OK Traitement avec document pdf"
                        R_AddMailInDBFromGovernance -S_PathArchiveAttachments $S_PathArchiveAttachments `
                                                    -B_FilePdf $true `
                                                    -O_CheckMail $O_CheckMail `
                                                    -S_Connectionstring $S_Connectionstring
                    }
                    elseif ($A_F_GetAttachmentsObject[0] -eq 1) {
                        Write-Host -ForegroundColor Green "OK Traitement sans document"
                        R_AddMailInDBFromGovernance -S_PathArchiveAttachments $S_PathArchiveAttachments `
                                                    -B_FilePdf $false `
                                                    -O_CheckMail $O_CheckMail `
                                                    -S_Connectionstring $S_Connectionstring
                    }
                    else {
                        Write-Host -ForegroundColor Green "Error"
                    }
                    
                    Write-Host -ForegroundColor Green $A_F_GetAttachmentsObject[1]
                    $O_CheckMail.Items.Move($O_FolderDONEMailAutomate.Id)
                }
                
                # Type 4: Mail non conforme
                else {
                    Write-Host -ForegroundColor Green "Format de mail non conforme ne devrait pas être dans ce répertoire."
                    Write-Host -ForegroundColor Green $O_CheckMail.Subject
                    Write-Host -ForegroundColor Green $O_CheckMail.From.Address
                    
                    R_Send-MailSmtp -Subject "ERROR processing WorkFlow Order [R_CheckReceivedMail], Mail not compliance for the process"
                    
                    $O_CheckMail.Items.Move($O_FolderERRORMailAutomate.Id)
                }
                
                $I_CountMailchecked++
                Start-Sleep -Seconds 10
                
            } Until ($I_CountMail -eq $I_CountMailchecked)
        }
        else {
            Write-Host -ForegroundColor Green "None Mail to do it"
        }
    }
    catch {
        Write-Host -ForegroundColor Red "Erreur lors du traitement: $_"
        Write-Host -ForegroundColor Red $_.Exception.Message
        Write-Host -ForegroundColor Red $_.ScriptStackTrace
    }
    finally {
        # Fermeture de la connexion ADODB
        $O_Connection.Close()
    }
}

<#
===========================================
EXEMPLE D'UTILISATION
===========================================
#>

# IMPORTANT: Vous devez d'abord vous connecter à Microsoft Graph
Connect-MgGraph -Scopes "Mail.ReadWrite", "Mail.ReadWrite.Shared"

# Import du module de wrappers
Import-Module .\EwsGraphWrappers.psm1 -Force

# Définir vos variables (exemple)
$S_PasswordExchange = "dummy"  # Plus utilisé mais gardé pour compatibilité
$S_ScriptPath = "C:\Scripts\"
$S_Connectionstring = "Provider=SQLOLEDB;Data Source=...;Initial Catalog=...;User ID=...;Password=..."

# Puis appeler votre fonction
R_CheckReceivedMail -S_Mail "emea.purchase.digital.workflow@bnpparibas.com" `
                    -S_LoginExchange "SVC.EMEAWINTEL.EWS" `
                    -S_PasswordExchange $S_PasswordExchange `
                    -S_Domain "MERCURY\" `
                    -S_FolderRoot "_01 AUTOMATE MAIL" `
                    -S_FolderProvider "DELL" `
                    -S_FolderSource "TODO" `
                    -S_FolderDestination "DONE" `
                    -S_FolderError "ERROR" `
                    -S_PathArchiveAttachments "$($S_ScriptPath)Attachments\" `
                    -S_Connectionstring $S_Connectionstring

<#
Note: Les paramètres S_LoginExchange, S_PasswordExchange et S_Domain ne sont plus 
utilisés avec Graph mais sont conservés pour maintenir la compatibilité de signature
#>