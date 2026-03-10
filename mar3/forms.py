from django import forms
from .models import ServerUnique
import datetime


# Form for Business Continuity Information
class BusinessContinuityInformationForm(forms.ModelForm):
    
    # Choices for priority asset, live play and cluster fields
    CHOICES_LIVE_PLAY = [
        ('YES', 'YES'),
        ('NO', 'NO'),
        ('EMPTY', 'EMPTY'),
    ]

    # Field for Priority Asset
    priority_asset = forms.ChoiceField( 
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="Is a Priority Asset",
        widget=forms.Select(attrs={'class': 'select-box'})
    )

    # Field for the Live Play status
    in_live_play = forms.ChoiceField( 
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="In Live Play",
        widget=forms.Select(attrs={'class': 'select-box'})
    )
    
    # Field for Cluster
    cluster = forms.ChoiceField( 
        choices=CHOICES_LIVE_PLAY,
        required=False,
        label="Cluster",
        widget=forms.Select(attrs={'class': 'select-box'})
    )

    # Field for Action During Live Play History
    action_during_lp_history = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'readonly': 'readonly', 'class': 'history-display'}),
        required=False,
        label="Action During Live Play Historic"
    )
    
    # Field for Original Action During Live Play History
    original_action_during_lp_history = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'readonly': 'readonly', 'class': 'history-display'}),
        required=False,
        label="Original Action During Live Play Historic"
    )
    

    # Meta class to specify the model and fields
    class Meta:
        model = ServerUnique
        fields = ['priority_asset', 'in_live_play', 'action_during_lp', 'original_action_during_lp', 'cluster', 'cluster_type']


    def __init__(self, *args, loggedonuser=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.loggedonuser = loggedonuser

        # Store original values for comparison
        self.previous_priority_asset = self.instance.priority_asset
        self.previous_in_live_play = self.instance.in_live_play
        self.previous_cluster = self.instance.cluster
        self.previous_cluster_type = self.instance.cluster_type
        self.previous_action_during_lp = self.instance.action_during_lp
        self.previous_action_during_lp_history = self.instance.action_during_lp_history
        self.previous_original_action_during_lp = self.instance.original_action_during_lp
        self.previous_original_action_during_lp_history = self.instance.original_action_during_lp_history
            
        if self.instance and self.instance.pk:
            self.fields['action_during_lp_history'].initial = self.instance.action_during_lp_history
            self.fields['original_action_during_lp_history'].initial = self.instance.original_action_during_lp_history

        # Update form attributes for action_during_lp, original_action_during_lp fields and cluster
        self.fields['action_during_lp'].widget.attrs.update({ 
            'placeholder': 'Enter the Action During LP...',
            'rows': 1
        })
            
        self.fields['original_action_during_lp'].widget.attrs.update({ 
            'placeholder': 'Enter the Original Action During LP...',
            'rows': 1
        })

        self.fields['cluster_type'].widget.attrs.update({ 
            'placeholder': 'Enter the Cluster Type...',
            'rows': 1
        })
        

    # Save method to handle form submission
    def save(self, commit=True):

        instance = super().save(commit=False)

        now_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_usr = self.loggedonuser
        now_str = f"[{now_date} - {now_usr}]"
        
        # Create a new history entry
        history_entry = {
            "date": now_date,
            "user": now_usr,
            "fromsource": "Single Edit",
            "changes": {}
        }

        # Update the Priority Asset field
        priority_asset_choice = self.cleaned_data.get('priority_asset')
        if priority_asset_choice:
            instance.priority_asset = priority_asset_choice
        history_entry["changes"]["priority_asset"] = {
            "old": self.previous_priority_asset,
            "new": self.instance.priority_asset if self.previous_priority_asset != self.instance.priority_asset else 'Not set or not modified'
        }
            
        # Update the Live Play status field
        in_live_play_choice = self.cleaned_data.get('in_live_play')
        if in_live_play_choice:
            instance.in_live_play = in_live_play_choice
        history_entry["changes"]["in_live_play"] = {
            "old": self.previous_in_live_play,
            "new": self.instance.in_live_play if self.previous_in_live_play != self.instance.in_live_play else 'Not set or not modified'
        }

        # Update the Action During Live Play and Action During Live Play History fields
        action_during_lp = self.cleaned_data.get('action_during_lp')
        if action_during_lp and action_during_lp != self.previous_action_during_lp:  # Check for non-empty string and compare with the previous value
            instance.action_during_lp = action_during_lp
            instance.action_during_lp_history = f"{now_str} {action_during_lp}\n" + (instance.action_during_lp_history or '')
            history_entry["changes"]["action_during_lp"] = {
                "info": "Has been edited, check its history"
            }
        else:
            instance.action_during_lp = self.previous_action_during_lp
            instance.action_during_lp_history = self.previous_action_during_lp_history
            history_entry["changes"]["action_during_lp"] = {
                "info": "Not set or not modified"
            }            

        # Update the Original Action During Live Play and Original Action During Live Play History fields
        original_action_during_lp = self.cleaned_data.get('original_action_during_lp')
        if original_action_during_lp and original_action_during_lp != self.previous_original_action_during_lp:  # Check for non-empty string and compare with the previous value
            instance.original_action_during_lp = original_action_during_lp
            instance.original_action_during_lp_history = f"{now_str} {original_action_during_lp}\n" + (instance.original_action_during_lp_history or '')
            history_entry["changes"]["original_action_during_lp"] = {
                "info": "Has been edited, check its history"
            }            
        else:
            instance.original_action_during_lp = self.previous_original_action_during_lp
            instance.original_action_during_lp_history = self.previous_original_action_during_lp_history
            history_entry["changes"]["original_action_during_lp"] = {
                "info": "Not set or not modified"
            }                 
        
        # Update the Cluster field
        cluster = self.cleaned_data.get('cluster')
        if cluster:
            instance.cluster = cluster
        history_entry["changes"]["cluster"] = {
            "old": self.previous_cluster,
            "new": self.instance.cluster if self.previous_cluster != self.instance.cluster else 'Not set or not modified'
        }

        # Update the Cluster Type field
        cluster_type = self.cleaned_data.get('cluster_type')
        if cluster_type:
            instance.cluster_type = cluster_type
        history_entry["changes"]["cluster_type"] = {
            "old": self.previous_cluster_type,
            "new": self.instance.cluster_type if self.previous_cluster_type != self.instance.cluster_type else 'Not set or not modified'
        }

        # Only add the history entry if there are changes
        if history_entry["changes"]:
            print("ici")
            instance.global_history.append(history_entry)
            
        if commit:
            instance.save()
        return instance


# Form for CSV file upload
class CsvUploadForm(forms.Form):
    csv_file = forms.FileField(label="Select a CSV file", widget=forms.FileInput(attrs={'accept': '.csv'}))
    
