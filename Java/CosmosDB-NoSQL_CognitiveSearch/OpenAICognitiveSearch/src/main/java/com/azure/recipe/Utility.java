package com.azure.recipe;

import com.azure.recipe.model.Recipe;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

public class Utility {

    public static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    public static List<Recipe> parseDocuments(String directoryPath) {
        List<Recipe> recipes = new ArrayList<>();
        File directory = new File(directoryPath);
        if (directory.isDirectory()) {
            File[] files = directory.listFiles();
            for (File file : files) {
                if (file.isFile() && file.getName().endsWith(".json")) {
                    try {
                        Recipe recipe = OBJECT_MAPPER.readValue(file, Recipe.class);
                        recipes.add(recipe);
                    } catch (IOException e) {
                        e.printStackTrace();
                    }
                }
            }
        }

        return recipes;
    }
}
