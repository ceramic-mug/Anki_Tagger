while
        echo -n "Trying again"
        # Call the external command
        python select_cards.py anki_embeddings.csv Pulm_learning_objectives.csv
        # $? is the return code, 0 if successful
        [ $? -ne 0 ]
do true ; done