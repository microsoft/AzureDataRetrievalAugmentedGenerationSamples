using Azure.Search.Documents.Indexes.Models;
using Azure.Search.Documents.Indexes;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace CosmosRecipeGuide
{

    public class CogSearchDoc
    {

        public string id { get; set; }
        public string name { get; set; }
        public string description { get; set; }
        public List<float> embedding { get; set; }        
    }     


}
