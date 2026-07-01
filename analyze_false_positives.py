import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
mapping_file = os.path.join(downloads_dir, "us_to_indian_procedure_mapping.csv")

df = pd.read_csv(mapping_file)
df_matches = df[df['pricing_source'] == 'PMJAY Assam Dataset Match'].copy()

# Compute string similarity (confidence score) using TF-IDF
vectorizer = TfidfVectorizer(stop_words='english')

scores = []
for _, row in df_matches.iterrows():
    us_title = str(row['us_procedure_title'])
    in_title = str(row['indian_procedure_equivalent'])
    
    try:
        tfidf = vectorizer.fit_transform([us_title, in_title])
        score = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
    except:
        score = 0.0
    scores.append(score)
    
df_matches['confidence_score'] = scores
df_matches = df_matches.sort_values('confidence_score', ascending=True)

# Count how many are below a reasonable threshold (e.g. 0.3)
suspicious_count = len(df_matches[df_matches['confidence_score'] < 0.3])
print(f"Total mapped: {len(df_matches)}")
print(f"Suspicious mappings (score < 0.3): {suspicious_count}")
print("\nTop 5 most suspicious:")
print(df_matches.head()[['us_procedure_title', 'indian_procedure_equivalent', 'confidence_score']])

df_matches.to_csv(os.path.join(downloads_dir, "suspicious_mappings_analysis.csv"), index=False)
