# ixd-vh-affective-system
A version of Kristiyan Balev's affective framework, integrated within the platform architecture for the Virtual Humans project at Interaction Design Lectorate (IxD) at Fontys UAS.

# To test the Kafka connection:
```bash
python tests\listen_output.py

python tests\test_init.py --vh_id happy_char --openness 0.8 --conscientiousness 0.7 --extraversion 0.9 --agreeableness 0.8 --neuroticism 0.1 --broker 192.168.120.200:9092

python tests\test_input.py --message "I feel great today!"
```