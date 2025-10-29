# Import du module de wrappers

Import-Module .\EwsGraphWrappers.psm1 -Force

<#
.SYNOPSIS
Version migrée stricte - structure identique au code original

.DESCRIPTION
Seuls les appels EWS ont été remplacés par Graph.
Toute la logique, les loops et les blocs restent identiques.
#>
Function R_CheckSendingGovernanceUK {
param(
[Parameter(Mandatory = $true)] [string]$S_Mail,
[Parameter(Mandatory = $true)] [string]$S_LoginExchange,
[Parameter(Mandatory = $true)] [string]$S_PasswordExchange,
[Parameter(Mandatory = $true)] [string]$S_Domain,
[Parameter(Mandatory = $true)] [string]$S_Connectionstring
)

```
$I_adOpenStatic = 3
$I_adLockOptimistic = 3
$O_Connection = New-Object -comobject ADODB.Connection
$O_Connection.Open($S_Connectionstring)
$O_RecordsetRead = New-Object -comobject ADODB.Recordset
$O_RecordsetReadSecond = New-Object -comobject ADODB.Recordset
$O_RecordsetUpdate = New-Object -comobject ADODB.Recordset

$O_RecordsetRead.Open(
    "select * from T_PurchaseCart where T_PurchaseCart_StateInt = 25 and T_PurchaseCart_Provider = 'DELL' and (T_PurchaseCart_Country = 'United Kingdom' or T_PurchaseCart_Country = 'GB')", 
    $O_Connection, 
    $I_adOpenStatic, 
    $I_adLockOptimistic
)

If (-Not $O_RecordsetRead.EOF) {
    $O_RecordsetReadSecond.Open(
        "select T_PurchaseSettings_Value from T_PurchaseSettings where T_PurchaseSettings_Type = 'MailSentToGovernanceUK'", 
        $O_Connection, 
        $I_adOpenStatic, 
        $I_adLockOptimistic
    )
    
    $O_RecordsetReadSecond.MoveFirst()
    $A_MailToGovernance = $($O_RecordsetReadSecond.Fields.Item("T_PurchaseSettings_Value").Value).split(",")
    $O_RecordsetReadSecond.Close()
    $O_RecordsetRead.MoveFirst()
    
    Do {
        # === CHANGEMENT : Graph au lieu de EWS ===
        # Remplace : $O_ExchService = New-Object Microsoft.Exchange.WebServices.Data.ExchangeService
        $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_Mail
        
        # Récupérer les infos du demandeur
        $O_RecordsetReadSecond.Open(
            "select T_LdapLoginTranslate_Mail, T_LdapLoginTranslate_Name from T_LdapLoginTranslate where T_LdapLoginTranslate_Login = '" + 
            $O_RecordsetRead.Fields.Item("T_PurchaseCart_Requester").Value + "'", 
            $O_Connection, 
            $I_adOpenStatic, 
            $I_adLockOptimistic
        )
        
        $O_RecordsetReadSecond.MoveFirst()
        $S_MailToRequester = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Mail").Value
        $S_NameToRequester = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Name").Value
        $O_RecordsetReadSecond.Close()
        
        # Récupérer les infos du validateur
        $O_RecordsetReadSecond.Open(
            "select T_LdapLoginTranslate_Mail, T_LdapLoginTranslate_Name from T_LdapLoginTranslate where T_LdapLoginTranslate_Login = '" + 
            $O_RecordsetRead.Fields.Item("T_PurchaseCart_ValidateManagerLevel1").Value + "'", 
            $O_Connection, 
            $I_adOpenStatic, 
            $I_adLockOptimistic
        )
        
        $S_MailToValidator = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Mail").Value
        $S_NameToValidator = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Name").Value
        $O_RecordsetReadSecond.Close()
        
        # Vérifier le délégué
        If ($O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value -ne "-") {
            $O_RecordsetReadSecond.Open(
                "select T_LdapLoginTranslate_Mail, T_LdapLoginTranslate_Name from T_LdapLoginTranslate where T_LdapLoginTranslate_Login = '" + 
                $O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value + "'", 
                $O_Connection, 
                $I_adOpenStatic, 
                $I_adLockOptimistic
            )
            
            $S_MailToDelegate = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Mail").Value
            $S_NameToDelegate = $O_RecordsetReadSecond.Fields.Item("T_LdapLoginTranslate_Name").Value
            $O_RecordsetReadSecond.Close()
        }
        
        # Récupérer les pièces jointes
        $O_RecordsetReadSecond.Open(
            "SELECT T_PurchaseMailReceived.T_PurchaseMailReceived_QuotationValid, T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_id, " + 
            "T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_AttachmentName, " + 
            "T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_RamdomFileName, " + 
            "T_PurchaseMailReceived.T_PurchaseMailReceived_Body, " + 
            "T_PurchaseMailReceived.T_PurchaseMailReceived_Subject, " + 
            "T_PurchaseMailReceived.T_PurchaseMailReceived_AttachmentCount, " + 
            "T_PurchaseMailReceived.T_PurchaseMailReceived_T_PurchaseCart_ID " + 
            "FROM T_PurchaseMailReceived " + 
            "INNER JOIN T_PurchaseMailReceivedAttachment ON T_PurchaseMailReceived.T_PurchaseMailReceived_ID = " + 
            "T_PurchaseMailReceivedAttachment.T_PurchaseMailReceivedAttachment_T_PurchaseMailReceived_ID " + 
            "where T_PurchaseMailReceived_QuotationValid = 'YES' And " + 
            "T_PurchaseMailReceived_T_PurchaseCart_ID = '" + 
            $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "'",
            $O_Connection, 
            $I_adOpenStatic, 
            $I_adLockOptimistic
        )
        
        $O_RecordsetReadSecond.MoveFirst()
        $A_FileAttachment = @()
        $S_HistoryMail = $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceived_Body").Value
        
        Do {
            $O_PSObject = New-Object PSObject
            
            Write-Log "R_CheckSendingGovernanceUK: AttachmentName: $($O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value)"
            
            $AttachmentName = "\\DFS\WebSite\wwwroot\Purchase\Attachment\" + $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_RamdomFileName").Value + ".pdf"
            
            Write-Log "R_CheckSendingGovernanceUK: AttachmentDestination: $AttachmentDestination"
            
            $AttachmentDestination = "\\DFS\Scripts\Purchase\Attachments\" + $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value
            
            Copy-Item $AttachmentName $AttachmentDestination
            
            Add-Member -InputObject $O_PSObject -MemberType NoteProperty -Name A_FileAttachment -Value `
                $("\\DFS\Scripts\Purchase\Attachments\" + $O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_AttachmentName").Value)
            
            Add-Member -InputObject $O_PSObject -MemberType NoteProperty -Name T_PurchaseMailReceivedAttachment_id -Value `
                $($O_RecordsetReadSecond.Fields.Item("T_PurchaseMailReceivedAttachment_id").Value)
            
            $A_FileAttachment += $O_PSObject
            $O_RecordsetReadSecond.MoveNext()
            
        } Until ($O_RecordsetReadSecond.EOF)
        
        $O_RecordsetReadSecond.Close()
        
        # Construction du message
        $O_message_Body = "Hello, <br><br>Could you please take in charge this quotation ?" + 
                        "<br>This order has been approved by $S_NameToValidator from the purchase workflow on FR side" + 
                        "<br>The requester is $S_NameToRequester .<br>Assigned Cost center is : <b>BAU</b>, Domain : " +
                        "<b>" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_BudgetDom").Value + "</b>, Cost Nature : " +
                        "<b>" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_BudgetCosNat").Value + "</b><br><br>" +
                        "Business sponsor is : " + $O_RecordsetRead.Fields.Item("T_PurchaseCart_RequesterTeam").Value + 
                        " For the TEAM : " + $O_RecordsetRead.Fields.Item("T_PurchaseCart_RequesterNameTeam").Value + 
                        "<br><br>This Mail has been sent by a bot, When you will have to raise a Purchase request in ITSM please add in the " +
                        "short description : '" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_ProjectName").Value + " [" + 
                        $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "]'" + 
                        "<br><br><br><br>Regards,<br>Portal Indus WorkFlow Purchase<br>emea.purchase.digital.workflow@bnpparibas.com<br>" +
                        "<br><br>$S_HistoryMail"
        
        # === CHANGEMENT : Création du message via Graph au lieu de EWS ===
        # Remplace : $O_message = New-Object Microsoft.Exchange.WebServices.Data.EmailMessage
        $S_message_Subject = "[FOR UK SOURCING] Order approved for the project nammed : " + 
                            $O_RecordsetRead.Fields.Item("T_PurchaseCart_ProjectName").Value
        
        # Préparer les destinataires To
        $toRecipients = @()
        ForEach ($S_ToRecipients in $A_MailToGovernance) {
            $toRecipients += $S_ToRecipients
        }
        
        # Préparer les destinataires Cc
        $ccRecipients = @()
        If ($S_MailToRequester -ne "KO") {
            $ccRecipients += $S_MailToRequester
        }
        $ccRecipients += $S_MailToValidator
        $ccRecipients += "mei.jeoubi@xxx.com"
        $ccRecipients += "syin.courdan@xxx.com"
        $ccRecipients += "fice.ous@xxx.com"
        $ccRecipients += "dl.uk.datacentre@uk.xxx.com"
        
        If ($O_RecordsetRead.Fields.Item("T_PurchaseCart_Delegation").Value -ne "-") {
            $ccRecipients += $S_MailToDelegate
        }
        
        # Préparer les pièces jointes
        $attachmentPaths = @()
        ForEach ($S_A_FileAttachment in $A_FileAttachment) {
            Write-Log "R_CheckSendingGovernanceUK: $($S_A_FileAttachment.A_FileAttachment)"
            $attachmentPaths += $S_A_FileAttachment.A_FileAttachment
        }
        
        # === CHANGEMENT : Envoi via Graph au lieu de EWS ===
        # Remplace : $O_message.SendAndSaveCopy()
        $result = Send-EwsCompatMessage -Subject $S_message_Subject `
                                        -Body $O_message_Body `
                                        -BodyType "HTML" `
                                        -ToRecipients $toRecipients `
                                        -CcRecipients $ccRecipients `
                                        -Attachments $attachmentPaths `
                                        -SaveToSentItems $true
        
        Start-Sleep -s 10
        
        ForEach ($S_A_FileAttachment in $A_FileAttachment) {
            Remove-Item $($S_A_FileAttachment.A_FileAttachment)
        }
        
        $O_RecordsetUpdate.Open(
            "update T_PurchaseCart set T_PurchaseCart_StateInt = '30', T_PurchaseCart_StateString = 'ORDER SENT GOVERNANCE' " + 
            "where T_PurchaseCart_ID = '" + $O_RecordsetRead.Fields.Item("T_PurchaseCart_ID").Value + "'", 
            $O_Connection, 
            $I_adOpenStatic, 
            $I_adLockOptimistic
        )
        
        $O_RecordsetRead.MoveNext()
        
    } Until ($O_RecordsetRead.EOF)
}

$O_RecordsetRead.Close()
$O_Connection.Close()
```

}

# <#

# EXEMPLE D’UTILISATION

#>

# Connexion Graph

Connect-MgGraph -ClientId $ClientId -TenantId $TenantId -CertificateThumbprint $Thumbprint

# Import du module

Import-Module .\EwsGraphWrappers.psm1 -Force

# Appel

R_CheckSendingGovernanceUK -S_Mail “emea.purchase.digital.workflow@bnpparibas.com” `-S_LoginExchange "SVC.EMEAWINTEL.EWS"`
-S_PasswordExchange “dummy” `-S_Domain "MERCURY\"`
-S_Connectionstring $S_Connectionstring

# <#

# CHANGEMENTS MINIMAUX - SEULEMENT EWS → GRAPH

LIGNE PAR LIGNE, VOICI CE QUI A CHANGÉ :

AVANT (EWS):
$O_ExchService = New-Object Microsoft.Exchange.WebServices.Data.ExchangeService -ArgumentList “Exchange2010_SP2”
$O_Credential = New-Object System.Net.NetworkCredential(…)
$O_ExchService.Credentials = $O_Credential
$O_ExchService.AutodiscoverUrl($S_Mail, {$true})
$O_ExchService.ImpersonatedUserId = New-Object Microsoft.Exchange.WebServices.Data.ImpersonatedUserId(…)

APRÈS (GRAPH):
$connectionResult = Initialize-EwsCompatConnection -UserEmail $S_Mail

-----

AVANT (EWS):
$O_message = New-Object Microsoft.Exchange.WebServices.Data.EmailMessage -ArgumentList $O_ExchService
$O_message.Subject = $S_message_Subject
$O_message.Body = $O_message_Body
ForEach($S_ToRecipients in $A_MailToGovernance){$O_message.ToRecipients.Add($S_ToRecipients)}
$O_message.CcRecipients.Add(…)
$O_message.Attachments.AddFileAttachment(…)
$O_message.SendAndSaveCopy()

APRÈS (GRAPH):
# Préparer les tableaux
$toRecipients = @()
ForEach($S_ToRecipients in $A_MailToGovernance){ $toRecipients += $S_ToRecipients }
$ccRecipients = @(…)
$attachmentPaths = @(…)

```
# Envoyer
Send-EwsCompatMessage -Subject $S_message_Subject `
                      -Body $O_message_Body `
                      -ToRecipients $toRecipients `
                      -CcRecipients $ccRecipients `
                      -Attachments $attachmentPaths
```

TOUT LE RESTE EST IDENTIQUE !

- Même structure de loops (Do…Until)
- Même logique de DB
- Même gestion des pièces jointes
- Même noms de variables
- Même ordre des opérations
  #>
