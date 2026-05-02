import pandas as pd
import os

def prepare_county_twfe_panel_data():
    """Prepare monthly county-level TWFE panel with employment, policy, and COVID data."""
    

    downloads = os.path.join(os.path.expanduser('~'), 'downloads')
    emp = pd.read_csv(os.path.join(downloads, 'Employment - County - Weekly.csv'), low_memory=False)
    policy = pd.read_csv(os.path.join(downloads, 'Policy Milestones - State.csv'), parse_dates=['date'])
    covid = pd.read_csv(os.path.join(downloads, 'COVID - State - Daily.csv'), low_memory=False)
    
    # Employment  
    emp.rename(columns={'countyfips': 'COUNTYFIP'}, inplace=True)
    emp['STATEFIP'] = (emp['COUNTYFIP'] // 1000).astype(int)
    emp['emp_incq1'] = pd.to_numeric(emp['emp_incq1'], errors='coerce')
    emp['year'] = pd.to_numeric(emp['year'], errors='coerce')
    emp['month'] = pd.to_numeric(emp['month'], errors='coerce')
    emp.dropna(subset=['year', 'month', 'STATEFIP', 'COUNTYFIP', 'emp_incq1'], inplace=True)
    emp['year_month'] = pd.to_datetime(emp[['year', 'month']].assign(day=1)).dt.to_period('M')
    emp_m = emp.groupby(['year_month', 'STATEFIP', 'COUNTYFIP'])['emp_incq1'].mean().reset_index()
    
    # COVID Severity Data
    covid.rename(columns={'statefips': 'STATEFIP'}, inplace=True)
    for c in ['year', 'month', 'day', 'hospitalized_count']:
        covid[c] = pd.to_numeric(covid[c], errors='coerce')
    covid.dropna(subset=['year', 'month', 'day', 'STATEFIP', 'hospitalized_count'], inplace=True)
    covid['year_month'] = pd.to_datetime(covid[['year', 'month', 'day']]).dt.to_period('M')
    covid_m = covid.groupby(['year_month', 'STATEFIP'])['hospitalized_count'].mean().reset_index()
    covid_m.rename(columns={'hospitalized_count': 'covid_severity'}, inplace=True)
    
    # Merge & Policy Variables 
    df = pd.merge(emp_m, covid_m, on=['year_month', 'STATEFIP'], how='inner')
    df['date'] = df['year_month'].dt.to_timestamp()

    policy_end = policy[policy['policy_description'].str.contains("ended emergency employment benefits", case=False, na=False)]
    cutoff = policy_end.set_index('statefips')['date']
    
    df['TreatState'] = df['STATEFIP'].isin(cutoff.index).astype(int)
    df['cutoff_date'] = df['STATEFIP'].map(cutoff)
    df['Post'] = (df['date'].dt.to_period('M') >= df['cutoff_date'].dt.to_period('M')).astype(int)
    df['Policy_DiD'] = df['TreatState'] * df['Post']
    
    # Final Output 
    out = df[['date', 'STATEFIP', 'COUNTYFIP', 'emp_incq1', 'Policy_DiD', 'covid_severity']].dropna()
    out.to_csv('twfe_panel_county_data.csv', index=False)
    print(f"Saved panel with {out.shape[0]} rows to twfe_panel_county_data.csv")

if __name__ == '__main__':
    prepare_county_twfe_panel_data()
