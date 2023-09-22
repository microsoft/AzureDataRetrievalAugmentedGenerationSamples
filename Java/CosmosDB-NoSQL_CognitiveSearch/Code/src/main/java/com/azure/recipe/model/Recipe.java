package com.azure.recipe.model;

import lombok.Data;

import java.util.List;

@Data
public class Recipe {
    public String id;
    public String name;
    public String description;
    public List<Double> embedding;
    public String cuisine;
    public String difficulty;
    public String prepTime;
    public String cookTime;
    public String totalTime;
    public int servings;
    public List<String> ingredients;
    public List<String> instructions;

}
